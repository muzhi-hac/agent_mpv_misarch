package mcpserver

import (
	"context"
	"net/http"

	"misarch-agent-gateway-go/internal/catalog"
	"misarch-agent-gateway-go/internal/order"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

const serverVersion = "0.1.0"

type CatalogService interface {
	ListProducts(ctx context.Context, topK int) (catalog.ListProductsOutput, error)

	GetProduct(ctx context.Context, productID string) (catalog.GetProductOutput, error)
}

type OrderService interface {
	CreatePendingOrder(
		ctx context.Context,
		input order.CreatePendingOrderInput,
	) (order.CreatePendingOrderOutput, error)
}

type ListProductsInput struct {
	TopK int `json:"top_k,omitempty" jsonschema:"maximum number of products to return; optional; default 5; allowed range 1 to 10"`
}

type GetProductInput struct {
	ProductID string `json:"product_id" jsonschema:"MiSArch product UUID returned by list_products"`
}

func New(service CatalogService) *mcp.Server {
	server := mcp.NewServer(
		&mcp.Implementation{
			Name:    "misarch-agent-gateway",
			Version: serverVersion,
		},
		nil,
	)

	registerTools(server, service)

	return server
}

func registerTools(server *mcp.Server, service CatalogService) {
	mcp.AddTool(
		server,
		&mcp.Tool{
			Name:        "list_products",
			Description: "List up to 10 public MiSArch catalog products. Read-only. No side effects.",
		},
		handleListProducts(service),
	)

	mcp.AddTool(
		server,
		&mcp.Tool{
			Name:        "get_product",
			Description: "Get one public MiSArch catalog product by UUID. Read-only. No side effects.",
		},
		handleGetProduct(service),
	)

}

func handleListProducts(service CatalogService) func(
	context.Context,
	*mcp.CallToolRequest,
	ListProductsInput,
) (*mcp.CallToolResult, catalog.ListProductsOutput, error) {
	return func(
		ctx context.Context,
		_ *mcp.CallToolRequest,
		input ListProductsInput,
	) (*mcp.CallToolResult, catalog.ListProductsOutput, error) {
		output, err := service.ListProducts(ctx, input.TopK)

		return nil, output, err
	}
}

func handleGetProduct(service CatalogService) func(
	context.Context,
	*mcp.CallToolRequest,
	GetProductInput,
) (*mcp.CallToolResult, catalog.GetProductOutput, error) {
	return func(
		ctx context.Context,
		_ *mcp.CallToolRequest,
		input GetProductInput,
	) (*mcp.CallToolResult, catalog.GetProductOutput, error) {
		output, err := service.GetProduct(ctx, input.ProductID)

		return nil, output, err
	}
}

func RegisterOrderTools(server *mcp.Server, service OrderService) {
	mcp.AddTool(
		server,
		&mcp.Tool{
			Name:        "create_pending_order",
			Description: "Create a pending MiSArch order for a selected product variant. Controlled side effect: creates a shopping cart item and pending order only; does not place the order or trigger payment.",
		},
		handleCreatePendingOrder(service),
	)
}

func handleCreatePendingOrder(service OrderService) func(
	context.Context,
	*mcp.CallToolRequest,
	order.CreatePendingOrderInput,
) (*mcp.CallToolResult, order.CreatePendingOrderOutput, error) {
	return func(
		ctx context.Context,
		_ *mcp.CallToolRequest,
		input order.CreatePendingOrderInput,
	) (*mcp.CallToolResult, order.CreatePendingOrderOutput, error) {
		output, err := service.CreatePendingOrder(ctx, input)

		return nil, output, err
	}
}

func NewHTTPHandler(server *mcp.Server) http.Handler {
	return mcp.NewStreamableHTTPHandler(
		func(*http.Request) *mcp.Server {
			return server
		},
		nil,
	)
}
