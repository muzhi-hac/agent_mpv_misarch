package order

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"
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

func validCompletePurchaseInput() CompletePurchaseInput {
	cvc := 123
	return CompletePurchaseInput{
		CreatePendingOrderInput: validInput(),
		PaymentCVC:              &cvc,
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

func TestCompletePurchasePlacesOrderAndWaitsForSimulatedPayment(t *testing.T) {
	const (
		cartID    = "550e8400-e29b-41d4-a716-446655440010"
		orderID   = "550e8400-e29b-41d4-a716-446655440011"
		paymentID = "550e8400-e29b-41d4-a716-446655440012"
	)
	gql := &fakeGraphQLClient{
		do: func(call int, out any) error {
			switch call {
			case 0:
				out.(*paymentStatusResponse).Payments.Nodes = []paymentNode{
					{ID: "550e8400-e29b-41d4-a716-446655440099", Status: "SUCCEEDED"},
				}
			case 1:
				out.(*createShoppingCartItemResponse).ShoppingCartItem = shoppingCartItemNode{
					ID: cartID,
				}
			case 2:
				out.(*createOrderResponse).Order = orderNode{
					ID: orderID, OrderStatus: "PENDING",
				}
			case 3:
				out.(*placeOrderResponse).Order = orderNode{
					ID: orderID, OrderStatus: "PLACED",
				}
			case 4:
				out.(*paymentStatusResponse).Payments.Nodes = []paymentNode{
					{ID: paymentID, Status: "PENDING"},
				}
			case 5:
				out.(*paymentStatusResponse).Payments.Nodes = []paymentNode{
					{ID: paymentID, Status: "SUCCEEDED"},
				}
			default:
				t.Fatalf("unexpected GraphQL call %d", call)
			}
			return nil
		},
	}

	service := NewService(gql, WithPaymentPolling(time.Second, time.Millisecond))
	got, err := service.CompletePurchase(context.Background(), validCompletePurchaseInput())
	if err != nil {
		t.Fatalf("CompletePurchase() returned error: %v", err)
	}
	if got.OrderID != orderID || got.OrderStatus != "PLACED" {
		t.Fatalf("order result = %+v, want order %s PLACED", got, orderID)
	}
	if got.ShoppingCartItemID != cartID {
		t.Fatalf("ShoppingCartItemID = %q, want %q", got.ShoppingCartItemID, cartID)
	}
	if got.PaymentID != paymentID || got.PaymentStatus != "SUCCEEDED" {
		t.Fatalf("payment result = %+v, want payment %s SUCCEEDED", got, paymentID)
	}
	if !strings.Contains(got.SideEffects, "locally simulated payment") {
		t.Fatalf("SideEffects = %q, want local simulation disclosure", got.SideEffects)
	}

	placeInput := gql.calls[3].variables["input"].(map[string]any)
	if placeInput["id"] != orderID {
		t.Fatalf("placeOrder id = %#v, want %q", placeInput["id"], orderID)
	}
	authorization := placeInput["paymentAuthorization"].(map[string]any)
	if authorization["cvc"] != 123 {
		t.Fatalf("paymentAuthorization.cvc = %#v, want 123", authorization["cvc"])
	}
	if gotFilter := gql.calls[0].variables["paymentInformationId"]; gotFilter != testPaymentInformationID {
		t.Fatalf("paymentInformationId filter = %#v, want %q", gotFilter, testPaymentInformationID)
	}
}

func TestCompletePurchaseStopsBeforePlaceOrderWhenCreateOrderFails(t *testing.T) {
	gql := &fakeGraphQLClient{
		do: func(call int, out any) error {
			if call == 0 {
				out.(*paymentStatusResponse).Payments.Nodes = nil
				return nil
			}
			if call == 1 {
				out.(*createShoppingCartItemResponse).ShoppingCartItem = shoppingCartItemNode{
					ID: "550e8400-e29b-41d4-a716-446655440010",
				}
				return nil
			}
			return errors.New("create order unavailable")
		},
	}

	_, err := NewService(gql).CompletePurchase(context.Background(), validCompletePurchaseInput())
	if err == nil || !strings.Contains(err.Error(), "create order unavailable") {
		t.Fatalf("CompletePurchase() error = %v, want create order error", err)
	}
	if len(gql.calls) != 3 {
		t.Fatalf("GraphQL calls = %d, want payment snapshot, cart, and createOrder", len(gql.calls))
	}
}

func TestCompletePurchaseReportsFailedSimulatedPayment(t *testing.T) {
	const orderID = "550e8400-e29b-41d4-a716-446655440011"
	gql := completePurchaseGraphQLFixture(t, orderID, "FAILED")

	_, err := NewService(gql).CompletePurchase(context.Background(), validCompletePurchaseInput())
	if err == nil || !strings.Contains(err.Error(), "status FAILED") {
		t.Fatalf("CompletePurchase() error = %v, want failed payment status", err)
	}
}

func TestCompletePurchasePaymentPollingTimesOut(t *testing.T) {
	const orderID = "550e8400-e29b-41d4-a716-446655440011"
	gql := completePurchaseGraphQLFixture(t, orderID, "PENDING")
	service := NewService(gql, WithPaymentPolling(4*time.Millisecond, time.Millisecond))

	_, err := service.CompletePurchase(context.Background(), validCompletePurchaseInput())
	if err == nil || !strings.Contains(err.Error(), "deadline exceeded") {
		t.Fatalf("CompletePurchase() error = %v, want bounded timeout", err)
	}
}

func TestCompletePurchaseRejectsInvalidCVC(t *testing.T) {
	input := validCompletePurchaseInput()
	invalid := 12
	input.PaymentCVC = &invalid

	_, err := NewService(&fakeGraphQLClient{}).CompletePurchase(context.Background(), input)
	if err == nil || !strings.Contains(err.Error(), "3 or 4 digits") {
		t.Fatalf("CompletePurchase() error = %v, want CVC validation error", err)
	}
}

func completePurchaseGraphQLFixture(
	t *testing.T,
	orderID string,
	paymentStatus string,
) *fakeGraphQLClient {
	t.Helper()
	return &fakeGraphQLClient{
		do: func(call int, out any) error {
			switch call {
			case 0:
				out.(*paymentStatusResponse).Payments.Nodes = nil
			case 1:
				out.(*createShoppingCartItemResponse).ShoppingCartItem = shoppingCartItemNode{
					ID: "550e8400-e29b-41d4-a716-446655440010",
				}
			case 2:
				out.(*createOrderResponse).Order = orderNode{
					ID: orderID, OrderStatus: "PENDING",
				}
			case 3:
				out.(*placeOrderResponse).Order = orderNode{
					ID: orderID, OrderStatus: "PLACED",
				}
			default:
				out.(*paymentStatusResponse).Payments.Nodes = []paymentNode{
					{ID: "550e8400-e29b-41d4-a716-446655440012", Status: paymentStatus},
				}
			}
			return nil
		},
	}
}
