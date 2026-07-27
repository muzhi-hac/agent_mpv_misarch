package order

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
)

const (
	maxQuantity = 3

	sourceService = "shoppingcart+order"
	runtimeName   = "misarch-graphql-gateway"
	sideEffects   = "creates a shopping cart item and a pending order; does not place the order or trigger payment"
	nextAction    = "Call confirm_place_order only after explicit user confirmation."

	completePurchaseSource      = "shoppingcart+order+payment+simulation"
	completePurchaseSideEffects = "creates a shopping cart item, creates and places an order, and completes a locally simulated payment"

	defaultPaymentPollTimeout  = 20 * time.Second
	defaultPaymentPollInterval = 250 * time.Millisecond
)

const createShoppingCartItemQuery = `
mutation CreateShoppingcartItem($input: CreateShoppingCartItemInput!) {
  createShoppingcartItem(input: $input) {
    id
    count
    productVariant {
      id
    }
  }
}`

const createOrderQuery = `
mutation CreateOrder($input: CreateOrderInput!) {
  createOrder(input: $input) {
    id
    orderStatus
  }
}`

const placeOrderQuery = `
mutation PlaceOrder($input: PlaceOrderInput!) {
  placeOrder(input: $input) {
    id
    orderStatus
  }
}`

const paymentStatusQuery = `
query PaymentStatus($paymentInformationId: String!) {
  payments(filter: {paymentInformationId: $paymentInformationId}) {
    nodes {
      id
      status
    }
  }
}`

type GraphQLClient interface {
	Do(
		ctx context.Context,
		query string,
		variables map[string]any,
		out any,
	) error
}

type Service struct {
	gql                 GraphQLClient
	paymentPollTimeout  time.Duration
	paymentPollInterval time.Duration
}

type ServiceOption func(*Service)

// WithPaymentPolling overrides how long CompletePurchase waits for MiSArch's
// asynchronous local payment simulation. It is primarily useful for tests and
// deployments with a customized simulation processing delay.
func WithPaymentPolling(timeout, interval time.Duration) ServiceOption {
	return func(service *Service) {
		service.paymentPollTimeout = timeout
		service.paymentPollInterval = interval
	}
}

type createShoppingCartItemResponse struct {
	ShoppingCartItem shoppingCartItemNode `json:"createShoppingcartItem"`
}

type shoppingCartItemNode struct {
	ID             string             `json:"id"`
	Count          int                `json:"count"`
	ProductVariant productVariantNode `json:"productVariant"`
}

type productVariantNode struct {
	ID string `json:"id"`
}

type createOrderResponse struct {
	Order orderNode `json:"createOrder"`
}

type placeOrderResponse struct {
	Order orderNode `json:"placeOrder"`
}

type orderNode struct {
	ID          string `json:"id"`
	OrderStatus string `json:"orderStatus"`
}

type paymentStatusResponse struct {
	Payments struct {
		Nodes []paymentNode `json:"nodes"`
	} `json:"payments"`
}

type paymentNode struct {
	ID     string `json:"id"`
	Status string `json:"status"`
}

func NewService(gql GraphQLClient, options ...ServiceOption) *Service {
	service := &Service{
		gql:                 gql,
		paymentPollTimeout:  defaultPaymentPollTimeout,
		paymentPollInterval: defaultPaymentPollInterval,
	}
	for _, option := range options {
		option(service)
	}
	return service
}

func (s *Service) CreatePendingOrder(
	ctx context.Context,
	input CreatePendingOrderInput,
) (CreatePendingOrderOutput, error) {
	if err := validateCreatePendingOrderInput(input); err != nil {
		return CreatePendingOrderOutput{}, err
	}

	shoppingCartItem, err := s.createShoppingCartItem(ctx, input)
	if err != nil {
		return CreatePendingOrderOutput{}, err
	}

	createdOrder, err := s.createOrder(ctx, input, shoppingCartItem.ID)
	if err != nil {
		return CreatePendingOrderOutput{}, err
	}

	return CreatePendingOrderOutput{
		OrderID:            createdOrder.ID,
		OrderStatus:        createdOrder.OrderStatus,
		ShoppingCartItemID: shoppingCartItem.ID,
		SourceService:      sourceService,
		Runtime:            runtimeName,
		SideEffects:        sideEffects,
		NextAction:         nextAction,
	}, nil
}

// CompletePurchase performs MiSArch's complete local checkout workflow. The
// final payment is processed by MiSArch's Simulation service; this code never
// contacts a real card network or external payment provider.
func (s *Service) CompletePurchase(
	ctx context.Context,
	input CompletePurchaseInput,
) (CompletePurchaseOutput, error) {
	if err := validateCompletePurchaseInput(input); err != nil {
		return CompletePurchaseOutput{}, err
	}

	existingPaymentIDs, err := s.paymentIDs(ctx, input.PaymentInformationID)
	if err != nil {
		return CompletePurchaseOutput{}, err
	}

	pending, err := s.CreatePendingOrder(ctx, input.CreatePendingOrderInput)
	if err != nil {
		return CompletePurchaseOutput{}, err
	}

	placed, err := s.placeOrder(ctx, pending.OrderID, input.PaymentCVC)
	if err != nil {
		return CompletePurchaseOutput{}, err
	}
	if placed.OrderStatus != "PLACED" {
		return CompletePurchaseOutput{}, fmt.Errorf(
			"place order: unexpected order status %q",
			placed.OrderStatus,
		)
	}

	payment, err := s.waitForPayment(ctx, input.PaymentInformationID, existingPaymentIDs)
	if err != nil {
		return CompletePurchaseOutput{}, err
	}

	return CompletePurchaseOutput{
		OrderID:            placed.ID,
		OrderStatus:        placed.OrderStatus,
		ShoppingCartItemID: pending.ShoppingCartItemID,
		PaymentID:          payment.ID,
		PaymentStatus:      payment.Status,
		SourceService:      completePurchaseSource,
		Runtime:            runtimeName,
		SideEffects:        completePurchaseSideEffects,
	}, nil
}

func (s *Service) createShoppingCartItem(
	ctx context.Context,
	input CreatePendingOrderInput,
) (shoppingCartItemNode, error) {
	var response createShoppingCartItemResponse
	err := s.gql.Do(
		ctx,
		createShoppingCartItemQuery,
		map[string]any{
			"input": map[string]any{
				"id": input.UserID,
				"shoppingCartItem": map[string]any{
					"count":            input.Quantity,
					"productVariantId": input.ProductVariantID,
				},
			},
		},
		&response,
	)
	if err != nil {
		return shoppingCartItemNode{}, fmt.Errorf("create shopping cart item: %w", err)
	}

	if response.ShoppingCartItem.ID == "" {
		return shoppingCartItemNode{}, fmt.Errorf("create shopping cart item: missing shopping cart item id")
	}

	return response.ShoppingCartItem, nil
}

func (s *Service) createOrder(
	ctx context.Context,
	input CreatePendingOrderInput,
	shoppingCartItemID string,
) (orderNode, error) {
	couponIDs := input.CouponIDs
	if couponIDs == nil {
		couponIDs = []string{}
	}

	var response createOrderResponse
	err := s.gql.Do(
		ctx,
		createOrderQuery,
		map[string]any{
			"input": map[string]any{
				"userId": input.UserID,
				"orderItemInputs": []map[string]any{
					{
						"shoppingCartItemId": shoppingCartItemID,
						"shipmentMethodId":   input.ShipmentMethodID,
						"couponIds":          couponIDs,
					},
				},
				"shipmentAddressId":    input.ShipmentAddressID,
				"invoiceAddressId":     input.InvoiceAddressID,
				"paymentInformationId": input.PaymentInformationID,
			},
		},
		&response,
	)
	if err != nil {
		return orderNode{}, fmt.Errorf("create pending order: %w", err)
	}

	if response.Order.ID == "" {
		return orderNode{}, fmt.Errorf("create pending order: missing order id")
	}

	return response.Order, nil
}

func (s *Service) placeOrder(
	ctx context.Context,
	orderID string,
	paymentCVC *int,
) (orderNode, error) {
	input := map[string]any{"id": orderID}
	if paymentCVC != nil {
		input["paymentAuthorization"] = map[string]any{"cvc": *paymentCVC}
	}

	var response placeOrderResponse
	if err := s.gql.Do(
		ctx,
		placeOrderQuery,
		map[string]any{"input": input},
		&response,
	); err != nil {
		return orderNode{}, fmt.Errorf("place order: %w", err)
	}
	if response.Order.ID == "" {
		return orderNode{}, fmt.Errorf("place order: missing order id")
	}
	return response.Order, nil
}

func (s *Service) waitForPayment(
	ctx context.Context,
	paymentInformationID string,
	existingPaymentIDs map[string]struct{},
) (paymentNode, error) {
	if s.paymentPollTimeout <= 0 || s.paymentPollInterval <= 0 {
		return paymentNode{}, fmt.Errorf("payment polling durations must be positive")
	}

	pollCtx, cancel := context.WithTimeout(ctx, s.paymentPollTimeout)
	defer cancel()

	for {
		payments, err := s.paymentStatuses(pollCtx, paymentInformationID)
		if err != nil {
			return paymentNode{}, err
		}

		for _, payment := range payments {
			if _, existed := existingPaymentIDs[payment.ID]; existed {
				continue
			}
			switch payment.Status {
			case "SUCCEEDED":
				return payment, nil
			case "FAILED", "INKASSO":
				return paymentNode{}, fmt.Errorf(
					"local simulated payment %s ended with status %s",
					payment.ID,
					payment.Status,
				)
			}
		}

		timer := time.NewTimer(s.paymentPollInterval)
		select {
		case <-pollCtx.Done():
			timer.Stop()
			return paymentNode{}, fmt.Errorf(
				"wait for new local simulated payment: %w",
				pollCtx.Err(),
			)
		case <-timer.C:
		}
	}
}

func (s *Service) paymentIDs(
	ctx context.Context,
	paymentInformationID string,
) (map[string]struct{}, error) {
	payments, err := s.paymentStatuses(ctx, paymentInformationID)
	if err != nil {
		return nil, err
	}
	ids := make(map[string]struct{}, len(payments))
	for _, payment := range payments {
		ids[payment.ID] = struct{}{}
	}
	return ids, nil
}

func (s *Service) paymentStatuses(
	ctx context.Context,
	paymentInformationID string,
) ([]paymentNode, error) {
	var response paymentStatusResponse
	err := s.gql.Do(
		ctx,
		paymentStatusQuery,
		map[string]any{"paymentInformationId": paymentInformationID},
		&response,
	)
	if err != nil {
		return nil, fmt.Errorf("query payment status: %w", err)
	}
	return response.Payments.Nodes, nil
}

func validateCreatePendingOrderInput(input CreatePendingOrderInput) error {
	if err := validateUUID("user_id", input.UserID); err != nil {
		return err
	}
	if err := validateUUID("product_variant_id", input.ProductVariantID); err != nil {
		return err
	}
	if err := validateUUID("shipment_method_id", input.ShipmentMethodID); err != nil {
		return err
	}
	if err := validateUUID("shipment_address_id", input.ShipmentAddressID); err != nil {
		return err
	}
	if err := validateUUID("invoice_address_id", input.InvoiceAddressID); err != nil {
		return err
	}
	if err := validateUUID("payment_information_id", input.PaymentInformationID); err != nil {
		return err
	}

	if input.Quantity < 1 || input.Quantity > maxQuantity {
		return fmt.Errorf("quantity must be between 1 and %d, got %d", maxQuantity, input.Quantity)
	}

	for _, couponID := range input.CouponIDs {
		if err := validateUUID("coupon_ids", couponID); err != nil {
			return err
		}
	}

	return nil
}

func validateCompletePurchaseInput(input CompletePurchaseInput) error {
	if err := validateCreatePendingOrderInput(input.CreatePendingOrderInput); err != nil {
		return err
	}
	if input.PaymentCVC != nil && (*input.PaymentCVC < 100 || *input.PaymentCVC > 9999) {
		return fmt.Errorf("payment_cvc must contain 3 or 4 digits")
	}
	return nil
}

func validateUUID(field string, value string) error {
	if err := uuid.Validate(value); err != nil {
		return fmt.Errorf("%s must be a valid UUID: %q: %w", field, value, err)
	}

	return nil
}
