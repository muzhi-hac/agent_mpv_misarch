package order

import (
	"context"
	"fmt"

	"github.com/google/uuid"
)

const (
	maxQuantity = 3

	sourceService = "shoppingcart+order"
	runtimeName   = "misarch-graphql-gateway"
	sideEffects   = "creates a shopping cart item and a pending order; does not place the order or trigger payment"
	nextAction    = "Call confirm_place_order only after explicit user confirmation."
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

type GraphQLClient interface {
	Do(
		ctx context.Context,
		query string,
		variables map[string]any,
		out any,
	) error
}

type Service struct {
	gql GraphQLClient
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

type orderNode struct {
	ID          string `json:"id"`
	OrderStatus string `json:"orderStatus"`
}

func NewService(gql GraphQLClient) *Service {
	return &Service{gql: gql}
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

func validateUUID(field string, value string) error {
	if err := uuid.Validate(value); err != nil {
		return fmt.Errorf("%s must be a valid UUID: %q: %w", field, value, err)
	}

	return nil
}
