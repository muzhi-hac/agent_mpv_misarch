package misarch

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

type staticTokenSource struct {
	token string
	err   error
}

func (s staticTokenSource) Token(ctx context.Context) (string, error) {
	return s.token, s.err
}

func TestClientDoSuccess(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Fatalf("method = %s, want POST", r.Method)
		}
		if got := r.Header.Get("Content-Type"); got != "application/json" {
			t.Fatalf("Content-Type = %q, want application/json", got)
		}
		var request GraphQLRequest
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			t.Fatalf("decode request %v", err)

		}
		if request.Query != "query Product { product { name } }" {
			t.Fatalf("query = %q", request.Query)
		}

		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"data":{"product":{"name":"Telescope"}}}`))

	}))

	defer server.Close()
	client := NewClient(server.URL, time.Second)
	var got struct {
		Product struct {
			Name string `json:"name"`
		} `json:"product"`
	}

	err := client.Do(context.Background(), "query Product { product { name } }", nil, &got)
	if err != nil {
		t.Fatalf("Do() returned error: %v", err)
	}
	if got.Product.Name != "Telescope" {
		t.Fatalf("product name = %q, want Telescope", got.Product.Name)
	}

}

func TestClientDoGraphQLError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"data": null,
			"errors": [
				{"message": "catalog query failed"}
			]
		}`))
	}))
	defer server.Close()

	client := NewClient(server.URL, time.Second)

	err := client.Do(context.Background(), "query { products { id } }", nil, &struct{}{})
	if err == nil {
		t.Fatal("Do() returned nil error, want GraphQL error")
	}

	if !strings.Contains(err.Error(), "catalog query failed") {
		t.Fatalf("error = %q, want GraphQL message", err)
	}
}

func TestClientDoAddsBearerToken(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if got := r.Header.Get("Authorization"); got != "Bearer test-token" {
			t.Fatalf("Authorization = %q, want Bearer test-token", got)
		}

		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"data":{"ok":true}}`))
	}))
	defer server.Close()

	client := NewClient(
		server.URL,
		time.Second,
		WithTokenSource(staticTokenSource{token: "test-token"}),
	)

	var got struct {
		OK bool `json:"ok"`
	}
	if err := client.Do(context.Background(), "query { ok }", nil, &got); err != nil {
		t.Fatalf("Do() returned error: %v", err)
	}
	if !got.OK {
		t.Fatal("OK = false, want true")
	}
}

func TestPasswordTokenSourceCachesToken(t *testing.T) {
	requests := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests++
		if err := r.ParseForm(); err != nil {
			t.Fatalf("ParseForm() error = %v", err)
		}
		if got := r.Form.Get("grant_type"); got != "password" {
			t.Fatalf("grant_type = %q, want password", got)
		}
		if got := r.Form.Get("client_id"); got != "frontend" {
			t.Fatalf("client_id = %q, want frontend", got)
		}
		if got := r.Form.Get("username"); got != "gatling" {
			t.Fatalf("username = %q, want gatling", got)
		}
		if got := r.Form.Get("password"); got != "123" {
			t.Fatalf("password = %q, want 123", got)
		}

		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"access_token": "cached-token",
			"token_type": "Bearer",
			"expires_in": 300
		}`))
	}))
	defer server.Close()

	source := NewPasswordTokenSource(server.URL, "frontend", "gatling", "123", time.Second)
	now := time.Date(2026, 6, 2, 12, 0, 0, 0, time.UTC)
	source.now = func() time.Time {
		return now
	}

	first, err := source.Token(context.Background())
	if err != nil {
		t.Fatalf("first Token() returned error: %v", err)
	}
	second, err := source.Token(context.Background())
	if err != nil {
		t.Fatalf("second Token() returned error: %v", err)
	}

	if first != "cached-token" || second != "cached-token" {
		t.Fatalf("tokens = %q, %q; want cached-token", first, second)
	}
	if requests != 1 {
		t.Fatalf("token endpoint requests = %d, want 1", requests)
	}
}

func TestClientReady(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var request GraphQLRequest
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
			t.Fatalf("decode request: %v", err)
		}

		if !strings.Contains(request.Query, "__typename") {
			t.Fatalf("query = %q, want __typename", request.Query)
		}

		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"data":{"__typename":"Query"}}`))
	}))
	defer server.Close()

	client := NewClient(server.URL, time.Second)

	if err := client.Ready(context.Background()); err != nil {
		t.Fatalf("Ready() returned error: %v", err)
	}
}
