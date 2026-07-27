# A2A Complete Simulated Purchase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the A2A `purchase` skill perform the complete MiSArch test purchase flow—cart item, `PENDING` order, `placeOrder`, and locally simulated payment—after explicit user confirmation.

**Architecture:** Keep MCP `create_pending_order` unchanged, and add a separate order-domain `CompletePurchase` operation for A2A. Before mutation, record the payment IDs already associated with the selected payment information; a confirmed A2A continuation then invokes `createShoppingcartItem`, `createOrder`, and `placeOrder`, and polls the federated Payment GraphQL view until a newly created payment reaches `SUCCEEDED` or a bounded timeout. MiSArch's local Simulation service supplies the payment result, so no external payment provider is involved.

**Tech Stack:** Go 1.25, official A2A Go SDK v2.3.1, MiSArch GraphQL federation, MiSArch Payment and Simulation services, Python 3 standard library.

---

### Task 1: Define and test the complete purchase domain operation

**Files:**
- Modify: `internal/order/types.go`
- Modify: `internal/order/service.go`
- Modify: `internal/order/service_test.go`

- [ ] **Step 1: Add failing service tests**

Add a fake GraphQL sequence that expects:

```text
createShoppingcartItem -> createOrder(PENDING) -> placeOrder(PLACED)
-> payments(empty/PENDING) -> payments(SUCCEEDED)
```

Assert the final output:

```go
CompletePurchaseOutput{
	OrderID:            testOrderID,
	OrderStatus:        "PLACED",
	ShoppingCartItemID: testCartID,
	PaymentID:          testPaymentID,
	PaymentStatus:      "SUCCEEDED",
}
```

Also assert that `confirmed=false` is handled by A2A rather than this domain method, `placeOrder` is never called after create-order failure, terminal payment failure returns an error, and polling timeout returns a bounded error.

- [ ] **Step 2: Run the focused test and verify failure**

Run:

```bash
go test ./internal/order -run 'CompletePurchase' -v
```

Expected: FAIL because `CompletePurchaseInput`, `CompletePurchaseOutput`, and `CompletePurchase` do not exist.

- [ ] **Step 3: Implement the complete purchase sequence**

Add:

```go
type CompletePurchaseInput struct {
	CreatePendingOrderInput
	PaymentCVC *int `json:"payment_cvc,omitempty"`
}

type CompletePurchaseOutput struct {
	OrderID            string `json:"order_id"`
	OrderStatus        string `json:"order_status"`
	ShoppingCartItemID string `json:"shopping_cart_item_id"`
	PaymentID          string `json:"payment_id"`
	PaymentStatus      string `json:"payment_status"`
	SourceService      string `json:"source_service"`
	Runtime            string `json:"runtime"`
	SideEffects        string `json:"side_effects"`
}
```

Implement `placeOrder` with:

```graphql
mutation PlaceOrder($input: PlaceOrderInput!) {
  placeOrder(input: $input) {
    id
    orderStatus
  }
}
```

Implement payment polling with:

```graphql
query PaymentStatus($paymentInformationId: String!) {
  payments(filter: {paymentInformationId: $paymentInformationId}) {
    nodes {
      id
      status
    }
  }
}
```

Snapshot existing payment IDs before creating the cart/order. Match a payment ID not present in that snapshot; MiSArch generates payment IDs independently from order IDs. Continue for `OPEN` and `PENDING`, succeed only on `SUCCEEDED`, and fail on `FAILED` or `INKASSO`.

- [ ] **Step 4: Run domain tests**

Run:

```bash
go test ./internal/order -run 'CompletePurchase|CreatePendingOrder' -v
```

Expected: PASS.

### Task 2: Connect confirmed A2A purchase to the complete operation

**Files:**
- Modify: `internal/a2aserver/types.go`
- Modify: `internal/a2aserver/server.go`
- Modify: `internal/a2aserver/server_test.go`
- Modify: `cmd/server/main.go`

- [ ] **Step 1: Add A2A confirmation tests**

Assert a complete input with `confirmed=false` returns `TASK_STATE_INPUT_REQUIRED` and makes zero purchase calls. Assert the same input with `confirmed=true` calls `CompletePurchase` once and returns:

```json
{
  "order_created": true,
  "order_placed": true,
  "payment_succeeded": true,
  "purchase": {
    "order_status": "PLACED",
    "payment_status": "SUCCEEDED"
  }
}
```

- [ ] **Step 2: Run the focused test and verify failure**

Run:

```bash
go test ./internal/a2aserver -run 'Purchase|DecodePurchase' -v
```

Expected: FAIL because A2A still validates a dry-run.

- [ ] **Step 3: Implement typed decoding and confirmed dispatch**

Decode:

```go
type purchaseTaskInput struct {
	UserID               string   `json:"user_id"`
	ProductVariantID     string   `json:"product_variant_id"`
	Quantity             int      `json:"quantity"`
	ShipmentMethodID     string   `json:"shipment_method_id"`
	ShipmentAddressID    string   `json:"shipment_address_id"`
	InvoiceAddressID     string   `json:"invoice_address_id"`
	PaymentInformationID string   `json:"payment_information_id"`
	CouponIDs            []string `json:"coupon_ids,omitempty"`
	PaymentCVC           *int     `json:"payment_cvc,omitempty"`
	Confirmed            bool     `json:"confirmed"`
}
```

Default omitted quantity to one. A missing required field returns input-required; an unconfirmed complete request returns an explicit confirmation prompt; a confirmed request calls `CompletePurchase`.

- [ ] **Step 4: Add official A2A continuation coverage**

Use `a2a.NewMessageForTask` to reference the input-required task and resend the immutable purchase fields with `confirmed=true`. Assert completion and one complete-purchase call.

- [ ] **Step 5: Run protocol tests**

Run:

```bash
go test ./internal/a2aserver -run 'Purchase|OfficialSDK' -v
go test ./...
go vet ./...
```

Expected: PASS.

### Task 3: Add a guarded live A2A purchase runner

**Files:**
- Create: `scripts/a2a_purchase_e2e.py`
- Create: `scripts/test_a2a_purchase_e2e.py`
- Modify: `.gitignore`

- [ ] **Step 1: Add backend-free runner tests**

Require both:

```text
--execute
--confirmation-text "CREATE AND PAY ONE LOCAL TEST ORDER"
```

Assert the first A2A message sends `confirmed=false`; the second references its `taskId` and `contextId` and sends `confirmed=true`; success requires `order_status=PLACED` and `payment_status=SUCCEEDED`.

- [ ] **Step 2: Implement the runner**

Accept the six MiSArch UUIDs, quantity, optional coupons, and optional numeric CVC. Write a JSON audit record containing task/context, cart item, order, and payment IDs without printing credentials or CVC.

- [ ] **Step 3: Run backend-free tests**

Run:

```bash
python3 -m unittest scripts.test_a2a_purchase_e2e scripts.test_a2a_protocol scripts.test_guardrail -v
```

Expected: PASS.

- [ ] **Step 4: Run one authorized local purchase**

Run:

```bash
python3 -m scripts.a2a_purchase_e2e \
  --a2a-url "$A2A_URL" \
  --user-id "$TEST_USER_ID" \
  --product-variant-id "$TEST_PRODUCT_VARIANT_ID" \
  --shipment-method-id "$TEST_SHIPMENT_METHOD_ID" \
  --shipment-address-id "$TEST_SHIPMENT_ADDRESS_ID" \
  --invoice-address-id "$TEST_INVOICE_ADDRESS_ID" \
  --payment-information-id "$TEST_PAYMENT_INFORMATION_ID" \
  --quantity 1 \
  --execute \
  --confirmation-text "CREATE AND PAY ONE LOCAL TEST ORDER" \
  --output tmp/a2a_purchase_e2e.json
```

Expected: one `PLACED` order and one local simulated `SUCCEEDED` payment. No external payment provider or real debit is contacted.

### Task 4: Document and verify the boundary

**Files:**
- Modify: `README.md`
- Modify: `docs/a2a-developer-guide.zh.md`

- [ ] **Step 1: Document MiSArch status semantics**

Document that the order state is `PLACED`; MiSArch represents paid state separately as `Payment.status=SUCCEEDED`, not as an order status named `PAID`.

- [ ] **Step 2: Document test side effects**

Document that the local live test consumes/reserves inventory, creates a cart item, order, payment, invoice, and downstream saga events, and that the repository has no verified cleanup transaction.

- [ ] **Step 3: Run final verification**

Run:

```bash
git diff --check
go test ./...
go vet ./...
python3 -m unittest scripts.test_a2a_purchase_e2e scripts.test_a2a_protocol scripts.test_guardrail -v
```

Expected: no whitespace errors and all tests PASS.
