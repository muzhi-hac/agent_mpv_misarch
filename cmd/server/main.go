package main

import (
	"log"
	"misarch-agent-gateway-go/internal/config"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		log.Fatal(err)
	}
	log.Printf("config loaded: http_addr=%s graphql_url=%s graphql_timeout=%s",
		cfg.HTTPAddr,
		cfg.GraphQLEndpoint,
		cfg.GraphQLTimeout)

}
