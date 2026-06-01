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
