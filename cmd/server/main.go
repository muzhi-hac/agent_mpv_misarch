package main

import (
	"context"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"misarch-agent-gateway-go/internal/catalog"
	"misarch-agent-gateway-go/internal/config"
	"misarch-agent-gateway-go/internal/httpserver"
	"misarch-agent-gateway-go/internal/mcpserver"
	"misarch-agent-gateway-go/internal/misarch"
)

func main() {
	if err := run(context.Background()); err != nil {
		log.Fatal(err)
	}
}

func run(ctx context.Context) error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}

	graphQLClient := misarch.NewClient(cfg.GraphQLEndpoint, cfg.GraphQLTimeout)
	catalogService := catalog.NewService(graphQLClient)

	mcpServer := mcpserver.New(catalogService)
	mcpHandler := mcpserver.NewHTTPHandler(mcpServer)
	handler := httpserver.NewHandler(mcpHandler, graphQLClient)

	server := &http.Server{
		Addr:              cfg.HTTPAddr,
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
	}

	ctx, stop := signal.NotifyContext(ctx, os.Interrupt, syscall.SIGTERM)
	defer stop()

	errs := make(chan error, 1)
	go func() {
		log.Printf("misarch agent gateway listening on %s", cfg.HTTPAddr)
		errs <- server.ListenAndServe()
	}()

	select {
	case <-ctx.Done():
		return shutdown(server)
	case err := <-errs:
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return err
	}
}

func shutdown(server *http.Server) error {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	return server.Shutdown(ctx)
}
