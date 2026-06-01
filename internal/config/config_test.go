package config

import (
	"testing"
	"time"
)

func TestLoadUsesDefaults(t *testing.T) {
	t.Setenv("HTTP_ADDR", "")
	t.Setenv("MISARCH_GRAPHQL_URL", "")
	t.Setenv("MISARCH_GRAPHQL_TIMEOUT", "")

	got, err := Load()
	if err != nil {
		t.Fatalf("Load() returned error: %v", err)
	}

	if got.HTTPAddr != "127.0.0.1:8001" {
		t.Fatalf("HTTPAddr = %q, want %q", got.HTTPAddr, "127.0.0.1:8001")
	}

	if got.GraphQLEndpoint != "http://localhost:8080/graphql" {
		t.Fatalf("GraphQLEndpoint = %q", got.GraphQLEndpoint)
	}

	if got.GraphQLTimeout != 3*time.Second {
		t.Fatalf("GraphQLTimeout = %s, want %s", got.GraphQLTimeout, 3*time.Second)
	}
}

func TestLoadReadsEnvironmentVariables(t *testing.T) {
	t.Setenv("HTTP_ADDR", ":9000")
	t.Setenv("MISARCH_GRAPHQL_URL", "http://misarch-gateway:8080/graphql")
	t.Setenv("MISARCH_GRAPHQL_TIMEOUT", "5s")

	got, err := Load()
	if err != nil {
		t.Fatalf("Load() returned error: %v", err)
	}

	if got.HTTPAddr != ":9000" {
		t.Fatalf("HTTPAddr = %q", got.HTTPAddr)
	}

	if got.GraphQLEndpoint != "http://misarch-gateway:8080/graphql" {
		t.Fatalf("GraphQLEndpoint = %q", got.GraphQLEndpoint)
	}

	if got.GraphQLTimeout != 5*time.Second {
		t.Fatalf("GraphQLTimeout = %s", got.GraphQLTimeout)
	}
}

func TestLoadRejectsInvalidEndpoint(t *testing.T) {
	t.Setenv("MISARCH_GRAPHQL_URL", "localhost:8080/graphql")

	_, err := Load()
	if err == nil {
		t.Fatal("Load() returned nil error, want invalid endpoint error")
	}
}

func TestLoadRejectsNonPositiveTimeout(t *testing.T) {
	t.Setenv("MISARCH_GRAPHQL_TIMEOUT", "0s")

	_, err := Load()
	if err == nil {
		t.Fatal("Load() returned nil error, want invalid timeout error")
	}
}
