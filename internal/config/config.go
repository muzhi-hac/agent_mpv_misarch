package config

import (
	"fmt"
	"net"
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
	PublicBaseURL   string
	Auth            AuthConfig
}

type AuthConfig struct {
	Enabled  bool
	TokenURL string
	ClientID string
	Username string
	Password string
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

	auth, err := loadAuthConfig()
	if err != nil {
		return Config{}, err
	}

	httpAddr := envOrDefault("HTTP_ADDR", defaultHTTPAddr)
	publicBaseURL := envOrDefault("PUBLIC_BASE_URL", defaultPublicBaseURL(httpAddr))
	if err := validateEndpoint(publicBaseURL); err != nil {
		return Config{}, fmt.Errorf("validate public base URL: %w", err)
	}

	return Config{
		HTTPAddr:        httpAddr,
		GraphQLEndpoint: endpoint,
		GraphQLTimeout:  timeout,
		PublicBaseURL:   publicBaseURL,
		Auth:            auth,
	}, nil

}

func envOrDefault(key string, fallback string) string {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	return value
}

func defaultPublicBaseURL(httpAddr string) string {
	host, port, err := net.SplitHostPort(httpAddr)
	if err != nil {
		return "http://" + httpAddr
	}

	if host == "" || host == "0.0.0.0" || host == "::" || host == "[::]" {
		host = "127.0.0.1"
	}

	return "http://" + net.JoinHostPort(host, port)
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

func loadAuthConfig() (AuthConfig, error) {
	tokenURL := os.Getenv("MISARCH_KEYCLOAK_TOKEN_URL")
	clientID := os.Getenv("MISARCH_KEYCLOAK_CLIENT_ID")
	username := os.Getenv("MISARCH_KEYCLOAK_USERNAME")
	password := os.Getenv("MISARCH_KEYCLOAK_PASSWORD")

	if tokenURL == "" && clientID == "" && username == "" && password == "" {
		return AuthConfig{}, nil
	}

	if tokenURL == "" || clientID == "" || username == "" || password == "" {
		return AuthConfig{}, fmt.Errorf("MISARCH_KEYCLOAK_TOKEN_URL, MISARCH_KEYCLOAK_CLIENT_ID, MISARCH_KEYCLOAK_USERNAME, and MISARCH_KEYCLOAK_PASSWORD must be set together")
	}

	if err := validateEndpoint(tokenURL); err != nil {
		return AuthConfig{}, fmt.Errorf("validate keycloak token URL: %w", err)
	}

	return AuthConfig{
		Enabled:  true,
		TokenURL: tokenURL,
		ClientID: clientID,
		Username: username,
		Password: password,
	}, nil
}
