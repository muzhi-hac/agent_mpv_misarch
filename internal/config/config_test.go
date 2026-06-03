package config

import (
	"testing"
	"time"
)

func TestLoadUsesDefaults(t *testing.T) {
	t.Setenv("HTTP_ADDR", "")
	t.Setenv("MISARCH_GRAPHQL_URL", "")
	t.Setenv("MISARCH_GRAPHQL_TIMEOUT", "")
	clearAuthEnv(t)

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
	if got.Auth.Enabled {
		t.Fatal("Auth.Enabled = true, want false")
	}
}

func TestLoadReadsEnvironmentVariables(t *testing.T) {
	t.Setenv("HTTP_ADDR", ":9000")
	t.Setenv("MISARCH_GRAPHQL_URL", "http://misarch-gateway:8080/graphql")
	t.Setenv("MISARCH_GRAPHQL_TIMEOUT", "5s")
	clearAuthEnv(t)

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

func TestLoadReadsAuthEnvironmentVariables(t *testing.T) {
	t.Setenv("MISARCH_KEYCLOAK_TOKEN_URL", "http://keycloak:80/keycloak/realms/Misarch/protocol/openid-connect/token")
	t.Setenv("MISARCH_KEYCLOAK_CLIENT_ID", "frontend")
	t.Setenv("MISARCH_KEYCLOAK_USERNAME", "gatling")
	t.Setenv("MISARCH_KEYCLOAK_PASSWORD", "123")

	got, err := Load()
	if err != nil {
		t.Fatalf("Load() returned error: %v", err)
	}

	if !got.Auth.Enabled {
		t.Fatal("Auth.Enabled = false, want true")
	}
	if got.Auth.TokenURL != "http://keycloak:80/keycloak/realms/Misarch/protocol/openid-connect/token" {
		t.Fatalf("TokenURL = %q", got.Auth.TokenURL)
	}
	if got.Auth.ClientID != "frontend" {
		t.Fatalf("ClientID = %q", got.Auth.ClientID)
	}
	if got.Auth.Username != "gatling" {
		t.Fatalf("Username = %q", got.Auth.Username)
	}
	if got.Auth.Password != "123" {
		t.Fatalf("Password = %q", got.Auth.Password)
	}
}

func TestLoadRejectsInvalidEndpoint(t *testing.T) {
	t.Setenv("MISARCH_GRAPHQL_URL", "localhost:8080/graphql")
	clearAuthEnv(t)

	_, err := Load()
	if err == nil {
		t.Fatal("Load() returned nil error, want invalid endpoint error")
	}
}

func TestLoadRejectsNonPositiveTimeout(t *testing.T) {
	t.Setenv("MISARCH_GRAPHQL_TIMEOUT", "0s")
	clearAuthEnv(t)

	_, err := Load()
	if err == nil {
		t.Fatal("Load() returned nil error, want invalid timeout error")
	}
}

func TestLoadRejectsPartialAuthConfig(t *testing.T) {
	t.Setenv("MISARCH_KEYCLOAK_TOKEN_URL", "http://keycloak/token")
	t.Setenv("MISARCH_KEYCLOAK_CLIENT_ID", "")
	t.Setenv("MISARCH_KEYCLOAK_USERNAME", "")
	t.Setenv("MISARCH_KEYCLOAK_PASSWORD", "")

	_, err := Load()
	if err == nil {
		t.Fatal("Load() returned nil error, want partial auth config error")
	}
}

func clearAuthEnv(t *testing.T) {
	t.Helper()

	t.Setenv("MISARCH_KEYCLOAK_TOKEN_URL", "")
	t.Setenv("MISARCH_KEYCLOAK_CLIENT_ID", "")
	t.Setenv("MISARCH_KEYCLOAK_USERNAME", "")
	t.Setenv("MISARCH_KEYCLOAK_PASSWORD", "")
}
