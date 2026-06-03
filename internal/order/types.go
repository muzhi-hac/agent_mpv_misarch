package order

type CreatePendingOrderInput struct {
	UserID               string   `json:"user_id" jsonschema:"MiSArch user UUID owning the shopping cart and order"`
	ProductVariantID     string   `json:"product_variant_id" jsonschema:"MiSArch product variant UUID selected by the agent"`
	Quantity             int      `json:"quantity" jsonschema:"number of items to reserve in the pending order; allowed range 1 to 3"`
	ShipmentMethodID     string   `json:"shipment_method_id" jsonschema:"MiSArch shipment method UUID to use for this order item"`
	ShipmentAddressID    string   `json:"shipment_address_id" jsonschema:"MiSArch user address UUID where the order should be shipped"`
	InvoiceAddressID     string   `json:"invoice_address_id" jsonschema:"MiSArch user address UUID used for invoicing"`
	PaymentInformationID string   `json:"payment_information_id" jsonschema:"MiSArch payment information UUID; payment is not triggered by this tool"`
	CouponIDs            []string `json:"coupon_ids,omitempty" jsonschema:"optional MiSArch coupon UUIDs to attach to the order item"`
}

type CreatePendingOrderOutput struct {
	OrderID            string `json:"order_id"`
	OrderStatus        string `json:"order_status"`
	ShoppingCartItemID string `json:"shopping_cart_item_id"`
	SourceService      string `json:"source_service"`
	Runtime            string `json:"runtime"`
	SideEffects        string `json:"side_effects"`
	NextAction         string `json:"next_action"`
}
