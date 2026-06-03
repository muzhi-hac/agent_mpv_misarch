package order

import (
	"context"
	"errors"
	"strings"
	"testing"
)

const (
	testUserID               = "550e8400-e29b-41d4-a716-446655440000"
	testProductVariantID     = "550e8400-e29b-41d4-a716-446655440001"
	testShipmentMethodID     = "550e8400-e29b-41d4-a716-446655440002"
	testShipmentAddressID    = "550e8400-e29b-41d4-a716-446655440003"
	testInvoiceAddressID     = "550e8400-e29b-41d4-a716-446655440004"
	testPaymentInformationID = "550e8400-e29b-41d4-a716-446655440005"
	testCouponID             = "550e8400-e29b-41d4-a716-446655440006"
)

type graphQLCall struct {
	query     string
	variables map[string]any
}

type fakeGraphQLClient struct {
	calls []graphQLCall
	do    func(call int, out any) error
}

func (f *fakeGraphQLClient) Do(
	ctx context.Context,
	query string,
	variables map[string]any,
	out any,
) error {
	f.calls = append(f.calls, graphQLCall{query: query, variables: variables})

	return f.do(len(f.calls)-1, out)
}

func validInput() CreatePendingOrderInput {
	return CreatePendingOrderInput{
		UserID:               testUserID,
		ProductVariantID:     testProductVariantID,
		Quantity:             2,
		ShipmentMethodID:     testShipmentMethodID,
		ShipmentAddressID:    testShipmentAddressID,
		InvoiceAddressID:     testInvoiceAddressID,
		PaymentInformationID: testPaymentInformationID,
		CouponIDs:            []string{testCouponID},
	}
}

func TestCreatePendingOrder(t *testing.T) {
	gql := &fakeGraphQLClient{
		do: func(call int, out any) error {
			switch call {
			case 0:
				response := out.(*createShoppingCartItemResponse)
				response.ShoppingCartItem = shoppingCartItemNode{
					ID:    "550e8400-e29b-41d4-a716-446655440010",
					Count: 2,
					ProductVariant: productVariantNode{
						ID: testProductVariantID,
					},
				}
			case 1:
				response := out.(*createOrderResponse)
				response.Order = orderNode{
					ID:          "550e8400-e29b-41d4-a716-446655440011",
					OrderStatus: "PENDING",
				}
			default:
				t.Fatalf("unexpected GraphQL call %d", call)
			}

			return nil
		},
	}

	service := NewService(gql)

	got, err := service.CreatePendingOrder(context.Background(), validInput())
	if err != nil {
		t.Fatalf("CreatePendingOrder() returned error: %v", err)
	}

	if got.OrderID != "550e8400-e29b-41d4-a716-446655440011" {
		t.Fatalf("OrderID = %q", got.OrderID)
	}
	if got.OrderStatus != "PENDING" {
		t.Fatalf("OrderStatus = %q, want PENDING", got.OrderStatus)
	}
	if !strings.Contains(got.SideEffects, "does not place") {
		t.Fatalf("SideEffects = %q, want explicit non-placement", got.SideEffects)
	}

	if len(gql.calls) != 2 {
		t.Fatalf("GraphQL calls = %d, want 2", len(gql.calls))
	}

	cartInput := gql.calls[0].variables["input"].(map[string]any)
	cartItem := cartInput["shoppingCartItem"].(map[string]any)
	if cartInput["id"] != testUserID {
		t.Fatalf("shopping cart user id = %#v", cartInput["id"])
	}
	if cartItem["count"] != 2 {
		t.Fatalf("shopping cart count = %#v", cartItem["count"])
	}
	if cartItem["productVariantId"] != testProductVariantID {
		t.Fatalf("productVariantId = %#v", cartItem["productVariantId"])
	}

	orderInput := gql.calls[1].variables["input"].(map[string]any)
	orderItems := orderInput["orderItemInputs"].([]map[string]any)
	if orderInput["paymentInformationId"] != testPaymentInformationID {
		t.Fatalf("paymentInformationId = %#v", orderInput["paymentInformationId"])
	}
	if orderItems[0]["shoppingCartItemId"] != "550e8400-e29b-41d4-a716-446655440010" {
		t.Fatalf("shoppingCartItemId = %#v", orderItems[0]["shoppingCartItemId"])
	}
	if orderItems[0]["shipmentMethodId"] != testShipmentMethodID {
		t.Fatalf("shipmentMethodId = %#v", orderItems[0]["shipmentMethodId"])
	}
}

func TestCreatePendingOrderRejectsInvalidUUID(t *testing.T) {
	called := false
	gql := &fakeGraphQLClient{
		do: func(call int, out any) error {
			called = true
			return nil
		},
	}

	input := validInput()
	input.ProductVariantID = "not-a-uuid"

	_, err := NewService(gql).CreatePendingOrder(context.Background(), input)
	if err == nil {
		t.Fatal("CreatePendingOrder() returned nil error, want UUID validation error")
	}
	if called {
		t.Fatal("GraphQL client was called for invalid input")
	}
}

func TestCreatePendingOrderSendsEmptyCouponListWhenOmitted(t *testing.T) {
	var couponIDs any
	gql := &fakeGraphQLClient{}
	gql.do = func(call int, out any) error {
		switch call {
		case 0:
			response := out.(*createShoppingCartItemResponse)
			response.ShoppingCartItem = shoppingCartItemNode{
				ID: "550e8400-e29b-41d4-a716-446655440010",
			}
		case 1:
			orderInput := gql.calls[1].variables["input"].(map[string]any)
			orderItems := orderInput["orderItemInputs"].([]map[string]any)
			couponIDs = orderItems[0]["couponIds"]

			response := out.(*createOrderResponse)
			response.Order = orderNode{
				ID:          "550e8400-e29b-41d4-a716-446655440011",
				OrderStatus: "PENDING",
			}
		default:
			t.Fatalf("unexpected GraphQL call %d", call)
		}

		return nil
	}

	input := validInput()
	input.CouponIDs = nil

	_, err := NewService(gql).CreatePendingOrder(context.Background(), input)
	if err != nil {
		t.Fatalf("CreatePendingOrder() returned error: %v", err)
	}

	got, ok := couponIDs.([]string)
	if !ok {
		t.Fatalf("couponIds type = %T, want []string", couponIDs)
	}
	if len(got) != 0 {
		t.Fatalf("couponIds length = %d, want 0", len(got))
	}
}

func TestCreatePendingOrderRejectsUnsafeQuantity(t *testing.T) {
	input := validInput()
	input.Quantity = 4

	_, err := NewService(&fakeGraphQLClient{}).CreatePendingOrder(context.Background(), input)
	if err == nil {
		t.Fatal("CreatePendingOrder() returned nil error, want quantity validation error")
	}
}

func TestCreatePendingOrderStopsAfterCartError(t *testing.T) {
	gql := &fakeGraphQLClient{
		do: func(call int, out any) error {
			return errors.New("cart unavailable")
		},
	}

	_, err := NewService(gql).CreatePendingOrder(context.Background(), validInput())
	if err == nil {
		t.Fatal("CreatePendingOrder() returned nil error, want upstream error")
	}
	if len(gql.calls) != 1 {
		t.Fatalf("GraphQL calls = %d, want 1", len(gql.calls))
	}
	if !strings.Contains(err.Error(), "cart unavailable") {
		t.Fatalf("error = %q", err)
	}
}
