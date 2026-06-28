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

	"misarch-agent-gateway-go/internal/a2aserver"
	"misarch-agent-gateway-go/internal/catalog"
	"misarch-agent-gateway-go/internal/config"
	"misarch-agent-gateway-go/internal/httpserver"
	"misarch-agent-gateway-go/internal/mcpserver"
	"misarch-agent-gateway-go/internal/misarch"
	"misarch-agent-gateway-go/internal/order"
)

// storeAdapter bundles the existing catalog and order services behind the
// a2aserver.Service interface. Both concrete types are named Service, so they
// cannot be embedded together; the methods are forwarded explicitly instead.
type storeAdapter struct {
	catalog *catalog.Service
	order   *order.Service
}

func (a storeAdapter) ListProducts(ctx context.Context, topK int) (catalog.ListProductsOutput, error) {
	return a.catalog.ListProducts(ctx, topK)
}

func (a storeAdapter) GetProduct(ctx context.Context, productID string) (catalog.GetProductOutput, error) {
	return a.catalog.GetProduct(ctx, productID)
}

func (a storeAdapter) CreatePendingOrder(ctx context.Context, in order.CreatePendingOrderInput) (order.CreatePendingOrderOutput, error) {
	return a.order.CreatePendingOrder(ctx, in)
}

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

	clientOptions := []misarch.ClientOption{}
	if cfg.Auth.Enabled {
		tokenSource := misarch.NewPasswordTokenSource(
			cfg.Auth.TokenURL,
			cfg.Auth.ClientID,
			cfg.Auth.Username,
			cfg.Auth.Password,
			cfg.GraphQLTimeout,
		)
		clientOptions = append(clientOptions, misarch.WithTokenSource(tokenSource))
	}

	graphQLClient := misarch.NewClient(cfg.GraphQLEndpoint, cfg.GraphQLTimeout, clientOptions...)
	catalogService := catalog.NewService(graphQLClient)
	orderService := order.NewService(graphQLClient)

	mcpServer := mcpserver.New(catalogService)
	mcpserver.RegisterOrderTools(mcpServer, orderService)
	mcpHandler := mcpserver.NewHTTPHandler(mcpServer)

	storeCard := a2aserver.DefaultCard(cfg.PublicBaseURL)
	a2aHandler := a2aserver.NewHandler(storeAdapter{catalog: catalogService, order: orderService}, storeCard)

	handler := httpserver.NewHandler(mcpHandler, a2aHandler, graphQLClient)

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
