package config

import (
	"fmt"
	"net/url"
	"os"
	"time"
)

const (
	defaultHTTPAddr        = "127.0.0.1:8001"
	defaultGraphQLEndpoint = "http://localhost:8080/graphql"
	defaultGraphQLTimeout  = "3s"
)

type Config struct {
	HTTPAddr        string
	GraphQLEndpoint string
	GraphQLTimeout  time.Duration
}

func Load() (Config, error) {
	endpoint := envOrDefault("MISARCH_GRAPHQL_URL", defaultGraphQLEndpoint)
	if err := validateEndpoint(endpoint); err != nil {
		return Config{}, err
	}

	timeout, err := parsePositiveDuration(
		envOrDefault("MISARCH_GRAPHQL_TIMEOUT", defaultGraphQLTimeout),
	)
	if err != nil {
		return Config{}, err
	}

	return Config{
		HTTPAddr:        envOrDefault("HTTP_ADDR", defaultHTTPAddr),
		GraphQLEndpoint: endpoint,
		GraphQLTimeout:  timeout,
	}, nil

}

func envOrDefault(key string, fallback string) string {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	return value
}
func parsePositiveDuration(raw string) (time.Duration, error) {
	duration, err := time.ParseDuration(raw)
	if err != nil {
		return 0, fmt.Errorf("parse duration %q: %w", raw, err)
	}

	if duration <= 0 {
		return 0, fmt.Errorf("duration must be positive: %q", raw)
	}

	return duration, nil
}
func validateEndpoint(raw string) error {
	parsed, err := url.Parse(raw)
	if err != nil {
		return fmt.Errorf("parse graphql endpoint %q: %w", raw, err)
	}
	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return fmt.Errorf("graphql endpoint must use http or https: %q", raw)
	}

	if parsed.Host == "" {
		return fmt.Errorf("graphql endpoint must include a host: %q", raw)
	}
	return nil
}
