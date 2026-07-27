# A2A Confirmed Purchase and End-to-End Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the A2A purchase skill from a dry-run into an explicitly confirmed creation of one MiSArch `PENDING` order, and prove the complete A2A-to-GraphQL path with a guarded live test.

**Architecture:** The first A2A purchase message carries the complete order input with `confirmed=false` and returns `TASK_STATE_INPUT_REQUIRED` without calling GraphQL. A follow-up `SendMessage` references the same A2A `taskId` and `contextId`, repeats the immutable order input with `confirmed=true`, and invokes the existing `order.Service.CreatePendingOrder`. Unit tests use a fake service; the opt-in live test creates exactly one pending order in a dedicated test account and records its order/cart IDs.

**Tech Stack:** Go 1.25, official A2A Go SDK v2.3.1, MiSArch GraphQL, Python 3 standard library, Go `httptest`, Python `unittest`.

---

### Task 1: Decode a typed purchase command

**Files:**
- Modify: `internal/a2aserver/types.go`
- Modify: `internal/a2aserver/server.go`
- Test: `internal/a2aserver/server_test.go`

- [ ] **Step 1: Add the failing decode tests**

Add table tests that pass JSON-decoded task inputs and assert:

```go
want := purchaseTaskInput{
	UserID:               testUserID,
	ProductVariantID:     testProductVariantID,
	Quantity:             1,
	ShipmentMethodID:     testShipmentMethodID,
	ShipmentAddressID:    testShipmentAddressID,
	InvoiceAddressID:     testInvoiceAddressID,
	PaymentInformationID: testPaymentInformationID,
	Confirmed:            true,
}
```

Also assert that omitted quantity becomes `1`, malformed numeric fields fail, and coupon IDs remain a string slice.

- [ ] **Step 2: Run the focused test**

Run:

```bash
go test ./internal/a2aserver -run TestDecodePurchaseTaskInput -v
```

Expected: FAIL because `purchaseTaskInput` and `decodePurchaseTaskInput` do not exist.

- [ ] **Step 3: Add the typed input and JSON decoder**

Define:

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
	Confirmed            bool     `json:"confirmed"`
}
```

Decode by JSON round-tripping `TaskRequest.Input`; set `Quantity=1` only when it is omitted.

- [ ] **Step 4: Run the decode tests**

Run:

```bash
go test ./internal/a2aserver -run TestDecodePurchaseTaskInput -v
```

Expected: PASS.

### Task 2: Enforce confirmation and create the pending order

**Files:**
- Modify: `internal/a2aserver/server.go`
- Test: `internal/a2aserver/server_test.go`

- [ ] **Step 1: Replace the dry-run expectations with confirmation tests**

The unconfirmed test must assert:

```go
if resp.State != StateInputRequired {
	t.Fatalf("state = %q, want input-required", resp.State)
}
if svc.createOrderCalls != 0 {
	t.Fatalf("CreatePendingOrder called before confirmation")
}
```

The confirmed test must configure the fake output and assert:

```go
if svc.createOrderCalls != 1 {
	t.Fatalf("CreatePendingOrder calls = %d, want 1", svc.createOrderCalls)
}
if resp.Artifact["order_created"] != true {
	t.Fatalf("order_created = %v, want true", resp.Artifact["order_created"])
}
```

- [ ] **Step 2: Run the purchase tests**

Run:

```bash
go test ./internal/a2aserver -run Purchase -v
```

Expected: FAIL because complete inputs still return a dry-run and never call the service.

- [ ] **Step 3: Implement confirmed creation**

Change purchase dispatch to accept context and service:

```go
func handlePurchase(ctx context.Context, svc Service, req TaskRequest) TaskResponse
```

For invalid/missing fields, return `StateInputRequired`. For `Confirmed=false`, return:

```go
TaskResponse{
	TaskID:  req.TaskID,
	State:   StateInputRequired,
	Message: "Explicit confirmation is required before creating a pending order.",
	Artifact: map[string]any{
		"confirmation_required": true,
		"order_created":         false,
	},
}
```

For `Confirmed=true`, map the typed input to `order.CreatePendingOrderInput`, call `svc.CreatePendingOrder`, and return:

```go
TaskResponse{
	TaskID:  req.TaskID,
	State:   StateCompleted,
	Message: "Pending order created; payment was not triggered.",
	Artifact: map[string]any{
		"confirmation_required": true,
		"order_created":         true,
		"order":                 output,
	},
}
```

- [ ] **Step 4: Run the purchase and full Go suites**

Run:

```bash
go test ./internal/a2aserver -run Purchase -v
go test ./...
go vet ./...
```

Expected: PASS.

### Task 3: Exercise the standard A2A continuation

**Files:**
- Modify: `internal/a2aserver/server_test.go`

- [ ] **Step 1: Add an official-client multi-turn test**

Use the official A2A client to:

1. send the full purchase input with `confirmed=false`;
2. assert `TASK_STATE_INPUT_REQUIRED` and zero service calls;
3. send a new user Message with the returned `task.ID` and `task.ContextID`, the same order fields, and `confirmed=true`;
4. assert `TASK_STATE_COMPLETED`, exactly one service call, and an order artifact.

Construct the continuation with:

```go
message := a2a.NewMessageForTask(
	a2a.MessageRoleUser,
	task,
	a2a.NewDataPart(map[string]any{
		"skill": "purchase",
		"input": confirmedInput,
	}),
)
```

- [ ] **Step 2: Run the official interoperability test**

Run:

```bash
go test ./internal/a2aserver -run TestOfficialSDKPurchaseContinuation -v
```

Expected: PASS with one pending-order service call.

### Task 4: Add an opt-in live end-to-end purchase test

**Files:**
- Create: `scripts/a2a_purchase_e2e.py`
- Create: `scripts/test_a2a_purchase_e2e.py`
- Modify: `.gitignore`

- [ ] **Step 1: Add backend-free script tests**

Mock the A2A responses and assert the script refuses mutation unless both are supplied:

```text
--execute
--confirmation-text "CREATE ONE PENDING TEST ORDER"
```

Assert the first message has `confirmed=false`, the second references the returned task/context and has `confirmed=true`, and success requires `order_status == "PENDING"` plus non-empty order/cart IDs.

- [ ] **Step 2: Run the script tests**

Run:

```bash
python3 -m unittest scripts.test_a2a_purchase_e2e -v
```

Expected: FAIL because the live runner does not exist.

- [ ] **Step 3: Implement the guarded runner**

Require:

```text
--a2a-url
--user-id
--product-variant-id
--shipment-method-id
--shipment-address-id
--invoice-address-id
--payment-information-id
```

Accept `--quantity` in `[1,3]`, optional repeated `--coupon-id`, and write the result to a user-selected JSON path. Never print credentials. Exit non-zero unless the first response is input-required and the confirmed continuation returns a real `PENDING` order.

- [ ] **Step 4: Run the backend-free tests**

Run:

```bash
python3 -m unittest scripts.test_a2a_purchase_e2e scripts.test_a2a_protocol scripts.test_guardrail -v
```

Expected: PASS.

- [ ] **Step 5: Run one authorized live mutation**

Run only against the dedicated disposable test account:

```bash
python3 -m scripts.a2a_purchase_e2e \
  --a2a-url "$A2A_URL" \
  --user-id "$TEST_USER_ID" \
  --product-variant-id "$TEST_PRODUCT_VARIANT_ID" \
  --quantity 1 \
  --shipment-method-id "$TEST_SHIPMENT_METHOD_ID" \
  --shipment-address-id "$TEST_SHIPMENT_ADDRESS_ID" \
  --invoice-address-id "$TEST_INVOICE_ADDRESS_ID" \
  --payment-information-id "$TEST_PAYMENT_INFORMATION_ID" \
  --execute \
  --confirmation-text "CREATE ONE PENDING TEST ORDER" \
  --output tmp/a2a_purchase_e2e.json
```

Expected: one new `PENDING` order, no payment/placement call, and a JSON record containing its IDs.

### Task 5: Document the mutation boundary

**Files:**
- Modify: `README.md`
- Modify: `docs/a2a-developer-guide.zh.md`

- [ ] **Step 1: Document the two-message confirmation flow**

State that `purchase` creates a shopping cart item and one `PENDING` order only after an A2A continuation explicitly sets `confirmed=true`. It never places the order or triggers payment.

- [ ] **Step 2: Document the live-test data effect**

State that the live E2E test intentionally leaves one pending order in the dedicated test account because this repository has no verified delete/cancel mutation. Include the emitted order/cart IDs as the audit handle.

- [ ] **Step 3: Verify the final diff**

Run:

```bash
git diff --check
go test ./...
python3 -m unittest scripts.test_a2a_purchase_e2e scripts.test_a2a_protocol scripts.test_guardrail -v
```

Expected: no whitespace errors and all tests PASS.
