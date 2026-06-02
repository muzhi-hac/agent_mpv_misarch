package mcpserver

import (
	"context"
	"testing"

	"misarch-agent-gateway-go/internal/catalog"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

const testProductID = "550e8400-e29b-41d4-a716-446655440000"

type fakeCatalogService struct {
	listTopK     int
	getProductID string
}

func (f *fakeCatalogService) ListProducts(
	ctx context.Context,
	topK int,
) (catalog.ListProductsOutput, error) {
	f.listTopK = topK

	return catalog.ListProductsOutput{
		Products: []catalog.ProductSummary{
			{
				ProductID:        testProductID,
				VariantID:        "variant-1",
				Name:             "Beginner Telescope",
				RetailPriceCents: 12900,
				Currency:         "EUR",
				Categories:       []string{"Optics"},
			},
		},
		ReturnedCount: 1,
		SourceService: "catalog",
		Runtime:       "misarch-graphql-gateway",
		SideEffects:   "none (read-only)",
	}, nil
}

func (f *fakeCatalogService) GetProduct(
	ctx context.Context,
	productID string,
) (catalog.GetProductOutput, error) {
	f.getProductID = productID

	return catalog.GetProductOutput{
		Found: true,
		Product: &catalog.ProductDetail{
			ProductID:        productID,
			VariantID:        "variant-1",
			Name:             "Beginner Telescope",
			Description:      "A telescope for clear night skies.",
			RetailPriceCents: 12900,
			Currency:         "EUR",
			Categories:       []string{"Optics"},
		},
		SourceService: "catalog",
		Runtime:       "misarch-graphql-gateway",
		SideEffects:   "none (read-only)",
	}, nil
}

func connectClient(
	t *testing.T,
	server *mcp.Server,
) *mcp.ClientSession {
	t.Helper()

	ctx := context.Background()
	serverTransport, clientTransport := mcp.NewInMemoryTransports()

	serverSession, err := server.Connect(ctx, serverTransport, nil)
	if err != nil {
		t.Fatalf("connect server: %v", err)
	}

	client := mcp.NewClient(
		&mcp.Implementation{
			Name:    "test-client",
			Version: "0.1.0",
		},
		nil,
	)

	clientSession, err := client.Connect(ctx, clientTransport, nil)
	if err != nil {
		t.Fatalf("connect client: %v", err)
	}

	t.Cleanup(func() {
		_ = clientSession.Close()
		_ = serverSession.Close()
	})

	return clientSession
}

func TestServerListsTools(t *testing.T) {
	session := connectClient(t, New(&fakeCatalogService{}))

	result, err := session.ListTools(context.Background(), nil)
	if err != nil {
		t.Fatalf("ListTools() returned error: %v", err)
	}

	if len(result.Tools) != 2 {
		t.Fatalf("tool count = %d, want 2", len(result.Tools))
	}

	names := map[string]bool{}
	for _, tool := range result.Tools {
		names[tool.Name] = true

		if tool.InputSchema == nil {
			t.Fatalf("tool %q has no input schema", tool.Name)
		}
	}

	if !names["list_products"] {
		t.Fatal("list_products tool is missing")
	}

	if !names["get_product"] {
		t.Fatal("get_product tool is missing")
	}
}

func TestServerCallsListProducts(t *testing.T) {
	service := &fakeCatalogService{}
	session := connectClient(t, New(service))

	result, err := session.CallTool(
		context.Background(),
		&mcp.CallToolParams{
			Name: "list_products",
			Arguments: map[string]any{
				"top_k": 3,
			},
		},
	)
	if err != nil {
		t.Fatalf("CallTool() returned error: %v", err)
	}

	if result.IsError {
		t.Fatalf("CallTool() returned tool error: %#v", result.Content)
	}

	if service.listTopK != 3 {
		t.Fatalf("topK = %d, want 3", service.listTopK)
	}

	if result.StructuredContent == nil {
		t.Fatal("StructuredContent = nil")
	}
}

func TestServerCallsGetProduct(t *testing.T) {
	service := &fakeCatalogService{}
	session := connectClient(t, New(service))

	result, err := session.CallTool(
		context.Background(),
		&mcp.CallToolParams{
			Name: "get_product",
			Arguments: map[string]any{
				"product_id": testProductID,
			},
		},
	)
	if err != nil {
		t.Fatalf("CallTool() returned error: %v", err)
	}

	if result.IsError {
		t.Fatalf("CallTool() returned tool error: %#v", result.Content)
	}

	if service.getProductID != testProductID {
		t.Fatalf(
			"productID = %q, want %q",
			service.getProductID,
			testProductID,
		)
	}

	if result.StructuredContent == nil {
		t.Fatal("StructuredContent = nil")
	}
}
