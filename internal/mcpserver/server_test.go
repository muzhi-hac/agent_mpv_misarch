package mcpserver

import (
	"context"
	"encoding/json"
	"fmt"
	"reflect"
	"strings"
	"testing"

	"misarch-agent-gateway-go/internal/catalog"
	"misarch-agent-gateway-go/internal/order"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

const testProductID = "550e8400-e29b-41d4-a716-446655440000"

const rawGraphQLCreateShoppingCartItemBaseline = `
mutation CreateShoppingcartItem($input: CreateShoppingCartItemInput!) {
  createShoppingcartItem(input: $input) {
    id
    count
    productVariant {
      id
    }
  }
}`

const rawGraphQLCreateOrderBaseline = `
mutation CreateOrder($input: CreateOrderInput!) {
  createOrder(input: $input) {
    id
    orderStatus
  }
}`

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

type fakeOrderService struct {
	input order.CreatePendingOrderInput
}

type rawGraphQLCall struct {
	query     string
	variables map[string]any
}

type rawGraphQLBaselineClient struct {
	responses []map[string]any
	calls     []rawGraphQLCall
}

func (c *rawGraphQLBaselineClient) Do(
	ctx context.Context,
	query string,
	variables map[string]any,
	out any,
) error {
	c.calls = append(c.calls, rawGraphQLCall{query: query, variables: variables})

	call := len(c.calls) - 1
	if call >= len(c.responses) {
		return fmt.Errorf("unexpected raw GraphQL call %d", call)
	}

	data, ok := c.responses[call]["data"].(map[string]any)
	if !ok {
		return fmt.Errorf("raw GraphQL baseline response %d has no data object", call)
	}

	raw, err := json.Marshal(data)
	if err != nil {
		return fmt.Errorf("marshal raw GraphQL baseline data: %w", err)
	}
	if err := json.Unmarshal(raw, out); err != nil {
		return fmt.Errorf("unmarshal raw GraphQL baseline data: %w", err)
	}

	return nil
}

func (f *fakeOrderService) CreatePendingOrder(
	ctx context.Context,
	input order.CreatePendingOrderInput,
) (order.CreatePendingOrderOutput, error) {
	f.input = input

	return order.CreatePendingOrderOutput{
		OrderID:            "550e8400-e29b-41d4-a716-446655440100",
		OrderStatus:        "PENDING",
		ShoppingCartItemID: "550e8400-e29b-41d4-a716-446655440101",
		SourceService:      "shoppingcart+order",
		Runtime:            "misarch-graphql-gateway",
		SideEffects:        "creates a shopping cart item and a pending order; does not place the order or trigger payment",
		NextAction:         "Call confirm_place_order only after explicit user confirmation.",
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

func TestServerCanRegisterOrderTool(t *testing.T) {
	server := New(&fakeCatalogService{})
	RegisterOrderTools(server, &fakeOrderService{})
	session := connectClient(t, server)

	result, err := session.ListTools(context.Background(), nil)
	if err != nil {
		t.Fatalf("ListTools() returned error: %v", err)
	}

	names := map[string]bool{}
	for _, tool := range result.Tools {
		names[tool.Name] = true
	}

	if !names["create_pending_order"] {
		t.Fatal("create_pending_order tool is missing")
	}
}

func TestServerCallsCreatePendingOrder(t *testing.T) {
	server := New(&fakeCatalogService{})
	orderService := &fakeOrderService{}
	RegisterOrderTools(server, orderService)
	session := connectClient(t, server)

	result, err := session.CallTool(
		context.Background(),
		&mcp.CallToolParams{
			Name: "create_pending_order",
			Arguments: map[string]any{
				"user_id":                "550e8400-e29b-41d4-a716-446655440000",
				"product_variant_id":     "550e8400-e29b-41d4-a716-446655440001",
				"quantity":               2,
				"shipment_method_id":     "550e8400-e29b-41d4-a716-446655440002",
				"shipment_address_id":    "550e8400-e29b-41d4-a716-446655440003",
				"invoice_address_id":     "550e8400-e29b-41d4-a716-446655440004",
				"payment_information_id": "550e8400-e29b-41d4-a716-446655440005",
			},
		},
	)
	if err != nil {
		t.Fatalf("CallTool() returned error: %v", err)
	}

	if result.IsError {
		t.Fatalf("CallTool() returned tool error: %#v", result.Content)
	}

	if orderService.input.Quantity != 2 {
		t.Fatalf("quantity = %d, want 2", orderService.input.Quantity)
	}
	if orderService.input.ProductVariantID != "550e8400-e29b-41d4-a716-446655440001" {
		t.Fatalf("productVariantID = %q", orderService.input.ProductVariantID)
	}
	if result.StructuredContent == nil {
		t.Fatal("StructuredContent = nil")
	}
}

func TestHandleCreatePendingOrderMatchesRawGraphQLBaseline(t *testing.T) {
	input := order.CreatePendingOrderInput{
		UserID:               "550e8400-e29b-41d4-a716-446655440000",
		ProductVariantID:     "550e8400-e29b-41d4-a716-446655440001",
		Quantity:             2,
		ShipmentMethodID:     "550e8400-e29b-41d4-a716-446655440002",
		ShipmentAddressID:    "550e8400-e29b-41d4-a716-446655440003",
		InvoiceAddressID:     "550e8400-e29b-41d4-a716-446655440004",
		PaymentInformationID: "550e8400-e29b-41d4-a716-446655440005",
		CouponIDs:            []string{"550e8400-e29b-41d4-a716-446655440006"},
	}

	rawCartResponse := map[string]any{
		"data": map[string]any{
			"createShoppingcartItem": map[string]any{
				"id":    "550e8400-e29b-41d4-a716-446655440010",
				"count": 2,
				"productVariant": map[string]any{
					"id": input.ProductVariantID,
				},
			},
		},
	}
	rawOrderResponse := map[string]any{
		"data": map[string]any{
			"createOrder": map[string]any{
				"id":          "550e8400-e29b-41d4-a716-446655440011",
				"orderStatus": "PENDING",
			},
		},
	}
	rawGraphQL := &rawGraphQLBaselineClient{
		responses: []map[string]any{
			rawCartResponse,
			rawOrderResponse,
		},
	}

	handler := handleCreatePendingOrder(order.NewService(rawGraphQL))
	result, got, err := handler(context.Background(), nil, input)
	if err != nil {
		t.Fatalf("handleCreatePendingOrder() returned error: %v", err)
	}
	if result != nil {
		t.Fatalf("CallToolResult = %#v, want nil structured-output result", result)
	}

	rawCart := rawGraphQLObject(t, rawCartResponse, "createShoppingcartItem")
	rawOrder := rawGraphQLObject(t, rawOrderResponse, "createOrder")
	want := order.CreatePendingOrderOutput{
		OrderID:            rawGraphQLString(t, rawOrder, "id"),
		OrderStatus:        rawGraphQLString(t, rawOrder, "orderStatus"),
		ShoppingCartItemID: rawGraphQLString(t, rawCart, "id"),
		SourceService:      "shoppingcart+order",
		Runtime:            "misarch-graphql-gateway",
		SideEffects:        "creates a shopping cart item and a pending order; does not place the order or trigger payment",
		NextAction:         "Call confirm_place_order only after explicit user confirmation.",
	}
	if got != want {
		t.Fatalf("handleCreatePendingOrder() = %#v, want raw GraphQL baseline %#v", got, want)
	}

	if len(rawGraphQL.calls) != 2 {
		t.Fatalf("raw GraphQL calls = %d, want 2", len(rawGraphQL.calls))
	}
	if normalizeGraphQL(rawGraphQL.calls[0].query) != normalizeGraphQL(rawGraphQLCreateShoppingCartItemBaseline) {
		t.Fatalf(
			"first raw GraphQL query = %q, want baseline %q",
			rawGraphQL.calls[0].query,
			rawGraphQLCreateShoppingCartItemBaseline,
		)
	}
	if normalizeGraphQL(rawGraphQL.calls[1].query) != normalizeGraphQL(rawGraphQLCreateOrderBaseline) {
		t.Fatalf(
			"second raw GraphQL query = %q, want baseline %q",
			rawGraphQL.calls[1].query,
			rawGraphQLCreateOrderBaseline,
		)
	}

	wantCartVariables := map[string]any{
		"input": map[string]any{
			"id": input.UserID,
			"shoppingCartItem": map[string]any{
				"count":            input.Quantity,
				"productVariantId": input.ProductVariantID,
			},
		},
	}
	if !reflect.DeepEqual(rawGraphQL.calls[0].variables, wantCartVariables) {
		t.Fatalf(
			"CreateShoppingcartItem variables = %#v, want raw GraphQL baseline %#v",
			rawGraphQL.calls[0].variables,
			wantCartVariables,
		)
	}

	wantOrderVariables := map[string]any{
		"input": map[string]any{
			"userId": input.UserID,
			"orderItemInputs": []map[string]any{
				{
					"shoppingCartItemId": rawGraphQLString(t, rawCart, "id"),
					"shipmentMethodId":   input.ShipmentMethodID,
					"couponIds":          input.CouponIDs,
				},
			},
			"shipmentAddressId":    input.ShipmentAddressID,
			"invoiceAddressId":     input.InvoiceAddressID,
			"paymentInformationId": input.PaymentInformationID,
		},
	}
	if !reflect.DeepEqual(rawGraphQL.calls[1].variables, wantOrderVariables) {
		t.Fatalf(
			"CreateOrder variables = %#v, want raw GraphQL baseline %#v",
			rawGraphQL.calls[1].variables,
			wantOrderVariables,
		)
	}
}

func rawGraphQLObject(
	t *testing.T,
	response map[string]any,
	key string,
) map[string]any {
	t.Helper()

	data, ok := response["data"].(map[string]any)
	if !ok {
		t.Fatalf("raw GraphQL baseline response has no data object: %#v", response)
	}

	object, ok := data[key].(map[string]any)
	if !ok {
		t.Fatalf("raw GraphQL baseline data[%q] = %#v, want object", key, data[key])
	}

	return object
}

func rawGraphQLString(t *testing.T, object map[string]any, key string) string {
	t.Helper()

	value, ok := object[key].(string)
	if !ok {
		t.Fatalf("raw GraphQL baseline field %q = %#v, want string", key, object[key])
	}

	return value
}

func normalizeGraphQL(query string) string {
	return strings.Join(strings.Fields(query), " ")
}
