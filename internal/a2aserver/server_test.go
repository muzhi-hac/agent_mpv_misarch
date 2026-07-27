package a2aserver

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/a2aproject/a2a-go/v2/a2a"
	"github.com/a2aproject/a2a-go/v2/a2aclient"
	"github.com/a2aproject/a2a-go/v2/a2aclient/agentcard"

	"misarch-agent-gateway-go/internal/catalog"
	"misarch-agent-gateway-go/internal/order"
)

const (
	testUserID               = "11111111-1111-4111-8111-111111111111"
	testProductVariantID     = "22222222-2222-4222-8222-222222222222"
	testShipmentMethodID     = "33333333-3333-4333-8333-333333333333"
	testShipmentAddressID    = "44444444-4444-4444-8444-444444444444"
	testInvoiceAddressID     = "55555555-5555-4555-8555-555555555555"
	testPaymentInformationID = "66666666-6666-4666-8666-666666666666"
	testCouponID             = "77777777-7777-4777-8777-777777777777"
)

type fakeService struct {
	listOut                catalog.ListProductsOutput
	completePurchaseOut    order.CompletePurchaseOutput
	completePurchaseErr    error
	completePurchaseCalls  int
	lastCompletePurchaseIn order.CompletePurchaseInput
}

func (f *fakeService) ListProducts(ctx context.Context, topK int) (catalog.ListProductsOutput, error) {
	return f.listOut, nil
}

func (f *fakeService) GetProduct(ctx context.Context, productID string) (catalog.GetProductOutput, error) {
	return catalog.GetProductOutput{Found: true, Product: &catalog.ProductDetail{ProductID: productID}}, nil
}

func (f *fakeService) CompletePurchase(ctx context.Context, in order.CompletePurchaseInput) (order.CompletePurchaseOutput, error) {
	f.completePurchaseCalls++
	f.lastCompletePurchaseIn = in
	return f.completePurchaseOut, f.completePurchaseErr
}

func completePurchaseInput(confirmed bool) map[string]any {
	input := map[string]any{
		"user_id":                testUserID,
		"product_variant_id":     testProductVariantID,
		"quantity":               float64(2),
		"shipment_method_id":     testShipmentMethodID,
		"shipment_address_id":    testShipmentAddressID,
		"invoice_address_id":     testInvoiceAddressID,
		"payment_information_id": testPaymentInformationID,
		"coupon_ids":             []any{testCouponID},
		"confirmed":              confirmed,
	}
	if confirmed {
		input["payment_cvc"] = float64(123)
	}
	return input
}

func completePurchasePreview() map[string]any {
	input := completePurchaseInput(false)
	delete(input, "confirmed")
	return input
}

func TestSamePurchasePreviewTreatsNullAndEmptyCouponsAsEquivalent(t *testing.T) {
	expected := completePurchasePreview()
	expected["coupon_ids"] = nil
	actual := completePurchasePreview()
	actual["coupon_ids"] = []any{}

	if !samePurchasePreview(expected, actual) {
		t.Fatal("a stored null coupon list and confirmed empty coupon list should be equivalent")
	}
}

func TestSamePurchasePreviewRejectsIncompleteStoredPreview(t *testing.T) {
	expected := completePurchasePreview()
	delete(expected, "quantity")

	if samePurchasePreview(expected, completePurchasePreview()) {
		t.Fatal("a stored preview missing an immutable field should fail closed")
	}
}

func newTestHandler(svc Service) http.Handler {
	return NewHandler(svc, DefaultCard("http://example.test:8001"))
}

func postTask(t *testing.T, handler http.Handler, body string) TaskResponse {
	t.Helper()
	request := httptest.NewRequest(http.MethodPost, "/tasks", strings.NewReader(body))
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)

	var resp TaskResponse
	if err := json.Unmarshal(response.Body.Bytes(), &resp); err != nil {
		t.Fatalf("decode response: %v (body=%q)", err, response.Body.String())
	}
	return resp
}

type jsonRPCResponse struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      any             `json:"id"`
	Result  json.RawMessage `json:"result"`
	Error   *struct {
		Code    int    `json:"code"`
		Message string `json:"message"`
	} `json:"error"`
}

func postA2A(t *testing.T, handler http.Handler, id, method string, params any) jsonRPCResponse {
	t.Helper()
	body, err := json.Marshal(map[string]any{
		"jsonrpc": "2.0",
		"id":      id,
		"method":  method,
		"params":  params,
	})
	if err != nil {
		t.Fatalf("marshal JSON-RPC request: %v", err)
	}
	request := httptest.NewRequest(http.MethodPost, "/a2a", strings.NewReader(string(body)))
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("A2A-Version", "1.0")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 (body=%q)", response.Code, response.Body.String())
	}

	var rpcResp jsonRPCResponse
	if err := json.Unmarshal(response.Body.Bytes(), &rpcResp); err != nil {
		t.Fatalf("decode JSON-RPC response: %v (body=%q)", err, response.Body.String())
	}
	if rpcResp.Error != nil {
		t.Fatalf("JSON-RPC error = %+v", rpcResp.Error)
	}
	if rpcResp.JSONRPC != "2.0" || rpcResp.ID != id {
		t.Fatalf("JSON-RPC envelope = %+v, want version 2.0 and id %q", rpcResp, id)
	}
	return rpcResp
}

func sendA2ATask(t *testing.T, handler http.Handler, id, skill string, input map[string]any) *a2a.Task {
	t.Helper()
	resp := postA2A(t, handler, id, "SendMessage", map[string]any{
		"message": map[string]any{
			"messageId": "message-" + id,
			"role":      "ROLE_USER",
			"parts": []any{
				map[string]any{"data": map[string]any{"skill": skill, "input": input}},
			},
		},
	})
	var result struct {
		Task *a2a.Task `json:"task"`
	}
	if err := json.Unmarshal(resp.Result, &result); err != nil {
		t.Fatalf("decode send result: %v (result=%s)", err, resp.Result)
	}
	if result.Task == nil {
		t.Fatalf("send result missing task: %s", resp.Result)
	}
	return result.Task
}

func TestAgentCardServed(t *testing.T) {
	handler := newTestHandler(&fakeService{})

	request := httptest.NewRequest(http.MethodGet, "/.well-known/agent-card.json", nil)
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", response.Code)
	}

	var card a2a.AgentCard
	if err := json.Unmarshal(response.Body.Bytes(), &card); err != nil {
		t.Fatalf("decode card: %v", err)
	}
	if len(card.Skills) != 2 {
		t.Fatalf("skills = %d, want 2", len(card.Skills))
	}

	if len(card.SupportedInterfaces) != 1 {
		t.Fatalf("supported interfaces = %d, want 1", len(card.SupportedInterfaces))
	}
	if got := card.SupportedInterfaces[0].ProtocolBinding; got != a2a.TransportProtocolJSONRPC {
		t.Fatalf("protocol binding = %q, want JSONRPC", got)
	}
	if got := card.SupportedInterfaces[0].ProtocolVersion; got != a2a.Version {
		t.Fatalf("protocol version = %q, want %q", got, a2a.Version)
	}
	if got := card.SupportedInterfaces[0].URL; got != "http://example.test:8001/a2a" {
		t.Fatalf("interface URL = %q, want /a2a endpoint", got)
	}
	findSkill(t, card, "browse")
	findSkill(t, card, "purchase")

	purchaseRisk := riskForSkill(t, card, "purchase")
	if purchaseRisk["risk_level"] != "high" || purchaseRisk["requires_confirmation"] != true {
		t.Fatalf("purchase risk extension = %+v, want high risk requiring confirmation", purchaseRisk)
	}
}

func TestA2AMessageSendBrowseAndGetTask(t *testing.T) {
	svc := &fakeService{listOut: catalog.ListProductsOutput{
		Products: []catalog.ProductSummary{
			{ProductID: "p1", Name: "Steel Cup", RetailPriceCents: 2999},
			{ProductID: "p2", Name: "Dog Treats", RetailPriceCents: 599},
		},
	}}
	handler := newTestHandler(svc)

	task := sendA2ATask(t, handler, "rpc-browse", "browse", map[string]any{
		"query": "cup",
		"top_k": 5,
	})
	if task.Status.State != a2a.TaskStateCompleted {
		t.Fatalf("task state = %q, want completed", task.Status.State)
	}
	artifact := taskArtifactData(t, task)
	products, ok := artifact["products"].([]any)
	if !ok || len(products) != 1 {
		t.Fatalf("artifact products = %#v, want one cup", artifact["products"])
	}

	getResp := postA2A(t, handler, "rpc-get", "GetTask", map[string]any{"id": task.ID})
	var stored a2a.Task
	if err := json.Unmarshal(getResp.Result, &stored); err != nil {
		t.Fatalf("decode tasks/get result: %v (result=%s)", err, getResp.Result)
	}
	if stored.ID != task.ID || stored.Status.State != a2a.TaskStateCompleted {
		t.Fatalf("stored task = %+v, want completed task %q", stored, task.ID)
	}
}

func TestA2AMessageSendPurchaseNeedsInput(t *testing.T) {
	task := sendA2ATask(
		t,
		newTestHandler(&fakeService{}),
		"rpc-purchase",
		"purchase",
		map[string]any{"user_id": "u1"},
	)

	if task.Status.State != a2a.TaskStateInputRequired {
		t.Fatalf("task state = %q, want input-required", task.Status.State)
	}
	artifact := taskArtifactData(t, task)
	if artifact["missing_fields"] == nil {
		t.Fatalf("artifact missing missing_fields: %+v", artifact)
	}
}

func TestA2AMessageSendUnknownSkillFailsTask(t *testing.T) {
	task := sendA2ATask(
		t,
		newTestHandler(&fakeService{}),
		"rpc-unknown",
		"teleport",
		nil,
	)

	if task.Status.State != a2a.TaskStateFailed {
		t.Fatalf("task state = %q, want failed", task.Status.State)
	}
	if task.Status.Message == nil || len(task.Status.Message.Parts) == 0 ||
		!strings.Contains(task.Status.Message.Parts[0].Text(), "unknown skill") {
		t.Fatalf("task failure message = %+v, want unknown skill", task.Status.Message)
	}
}

func TestOfficialSDKClientInteroperates(t *testing.T) {
	svc := &fakeService{listOut: catalog.ListProductsOutput{
		Products: []catalog.ProductSummary{
			{ProductID: "p1", Name: "Steel Cup", RetailPriceCents: 2999},
		},
	}}
	var storeHandler http.Handler
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		storeHandler.ServeHTTP(w, r)
	}))
	defer server.Close()
	storeHandler = NewHandler(svc, DefaultCard(server.URL))

	card, err := agentcard.DefaultResolver.Resolve(t.Context(), server.URL)
	if err != nil {
		t.Fatalf("official resolver failed: %v", err)
	}
	client, err := a2aclient.NewFromCard(t.Context(), card)
	if err != nil {
		t.Fatalf("official client construction failed: %v", err)
	}
	message := a2a.NewMessage(
		a2a.MessageRoleUser,
		a2a.NewDataPart(map[string]any{
			"skill": "browse",
			"input": map[string]any{"query": "cup", "top_k": 5},
		}),
	)
	result, err := client.SendMessage(t.Context(), &a2a.SendMessageRequest{Message: message})
	if err != nil {
		t.Fatalf("official client SendMessage failed: %v", err)
	}
	task, ok := result.(*a2a.Task)
	if !ok {
		t.Fatalf("official client result = %T, want *a2a.Task", result)
	}
	if task.Status.State != a2a.TaskStateCompleted {
		t.Fatalf("official client task state = %q, want completed", task.Status.State)
	}
	artifact := taskArtifactData(t, task)
	if products, ok := artifact["products"].([]any); !ok || len(products) != 1 {
		t.Fatalf("official client artifact products = %#v, want one", artifact["products"])
	}
}

func TestOfficialSDKPurchaseContinuationCompletesLocalPayment(t *testing.T) {
	svc := &fakeService{completePurchaseOut: order.CompletePurchaseOutput{
		OrderID:            "order-1",
		OrderStatus:        "PLACED",
		ShoppingCartItemID: "cart-1",
		PaymentID:          "order-1",
		PaymentStatus:      "SUCCEEDED",
	}}
	var storeHandler http.Handler
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		storeHandler.ServeHTTP(w, r)
	}))
	defer server.Close()
	storeHandler = NewHandler(svc, DefaultCard(server.URL))

	card, err := agentcard.DefaultResolver.Resolve(t.Context(), server.URL)
	if err != nil {
		t.Fatalf("official resolver failed: %v", err)
	}
	client, err := a2aclient.NewFromCard(t.Context(), card)
	if err != nil {
		t.Fatalf("official client construction failed: %v", err)
	}

	unconfirmed := a2a.NewMessage(
		a2a.MessageRoleUser,
		a2a.NewDataPart(map[string]any{
			"skill": "purchase",
			"input": completePurchaseInput(false),
		}),
	)
	result, err := client.SendMessage(t.Context(), &a2a.SendMessageRequest{Message: unconfirmed})
	if err != nil {
		t.Fatalf("unconfirmed SendMessage failed: %v", err)
	}
	task, ok := result.(*a2a.Task)
	if !ok {
		t.Fatalf("unconfirmed result = %T, want *a2a.Task", result)
	}
	if task.Status.State != a2a.TaskStateInputRequired {
		t.Fatalf("unconfirmed state = %q, want input-required", task.Status.State)
	}
	if svc.completePurchaseCalls != 0 {
		t.Fatalf("CompletePurchase calls = %d before confirmation, want 0", svc.completePurchaseCalls)
	}

	confirmed := a2a.NewMessageForTask(
		a2a.MessageRoleUser,
		task,
		a2a.NewDataPart(map[string]any{
			"skill": "purchase",
			"input": completePurchaseInput(true),
		}),
	)
	result, err = client.SendMessage(t.Context(), &a2a.SendMessageRequest{Message: confirmed})
	if err != nil {
		t.Fatalf("confirmed SendMessage failed: %v", err)
	}
	task, ok = result.(*a2a.Task)
	if !ok {
		t.Fatalf("confirmed result = %T, want *a2a.Task", result)
	}
	if task.Status.State != a2a.TaskStateCompleted {
		t.Fatalf("confirmed state = %q, want completed", task.Status.State)
	}
	if svc.completePurchaseCalls != 1 {
		t.Fatalf("CompletePurchase calls = %d, want 1", svc.completePurchaseCalls)
	}
	artifact := taskArtifactData(t, task)
	if artifact["order_placed"] != true || artifact["payment_succeeded"] != true {
		t.Fatalf("confirmed artifact = %+v, want placed and paid", artifact)
	}

	replay := a2a.NewMessageForTask(
		a2a.MessageRoleUser,
		task,
		a2a.NewDataPart(map[string]any{
			"skill": "purchase",
			"input": completePurchaseInput(true),
		}),
	)
	if _, err := client.SendMessage(t.Context(), &a2a.SendMessageRequest{Message: replay}); err == nil {
		t.Fatal("replaying a completed purchase task returned nil error, want terminal-task rejection")
	}
	if svc.completePurchaseCalls != 1 {
		t.Fatalf("CompletePurchase calls after replay = %d, want 1", svc.completePurchaseCalls)
	}
}

func TestOfficialSDKPurchaseContinuationRejectsPreviewTampering(t *testing.T) {
	svc := &fakeService{}
	var storeHandler http.Handler
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		storeHandler.ServeHTTP(w, r)
	}))
	defer server.Close()
	storeHandler = NewHandler(svc, DefaultCard(server.URL))

	card, err := agentcard.DefaultResolver.Resolve(t.Context(), server.URL)
	if err != nil {
		t.Fatalf("official resolver failed: %v", err)
	}
	client, err := a2aclient.NewFromCard(t.Context(), card)
	if err != nil {
		t.Fatalf("official client construction failed: %v", err)
	}

	result, err := client.SendMessage(t.Context(), &a2a.SendMessageRequest{
		Message: a2a.NewMessage(
			a2a.MessageRoleUser,
			a2a.NewDataPart(map[string]any{
				"skill": "purchase",
				"input": completePurchaseInput(false),
			}),
		),
	})
	if err != nil {
		t.Fatalf("unconfirmed SendMessage failed: %v", err)
	}
	task, ok := result.(*a2a.Task)
	if !ok {
		t.Fatalf("unconfirmed result = %T, want *a2a.Task", result)
	}

	tampered := completePurchaseInput(true)
	tampered["quantity"] = float64(3)
	result, err = client.SendMessage(t.Context(), &a2a.SendMessageRequest{
		Message: a2a.NewMessageForTask(
			a2a.MessageRoleUser,
			task,
			a2a.NewDataPart(map[string]any{
				"skill": "purchase",
				"input": tampered,
			}),
		),
	})
	if err != nil {
		t.Fatalf("tampered continuation returned transport error: %v", err)
	}
	task, ok = result.(*a2a.Task)
	if !ok {
		t.Fatalf("tampered continuation result = %T, want *a2a.Task", result)
	}
	if task.Status.State != a2a.TaskStateFailed {
		t.Fatalf("tampered continuation state = %q, want failed", task.Status.State)
	}
	if svc.completePurchaseCalls != 0 {
		t.Fatalf("CompletePurchase calls = %d, want 0 after preview tampering", svc.completePurchaseCalls)
	}
}

func TestBrowseReturnsCandidates(t *testing.T) {
	svc := &fakeService{listOut: catalog.ListProductsOutput{
		Products:      []catalog.ProductSummary{{ProductID: "p1", Name: "Steel Cup"}},
		ReturnedCount: 1,
	}}
	handler := newTestHandler(svc)

	resp := postTask(t, handler, `{"task_id":"t1","skill":"browse","input":{"top_k":5}}`)

	if resp.State != StateCompleted {
		t.Fatalf("state = %q, want completed", resp.State)
	}
	if resp.Artifact["products"] == nil {
		t.Fatalf("artifact missing products: %+v", resp.Artifact)
	}
}

func TestBrowseFiltersByQuery(t *testing.T) {
	svc := &fakeService{listOut: catalog.ListProductsOutput{
		Products: []catalog.ProductSummary{
			{ProductID: "p1", Name: "HydroRun Stainless Steel Cup", Categories: []string{"Home & Kitchen"}},
			{ProductID: "p2", Name: "Crunchy Chicken Dog Treats", Categories: []string{"Pet Supplies"}},
			{ProductID: "p3", Name: "GlidePro Wireless Mouse", Categories: []string{"Electronics & Gadgets"}},
			// Token-prefix matching must NOT let "phone" match "Headphones".
			{ProductID: "p4", Name: "Aurora Noise-Cancelling Headphones", Categories: []string{"Electronics & Gadgets"}},
		},
	}}
	handler := newTestHandler(svc)

	// A matching query narrows to the relevant candidate(s) only.
	resp := postTask(t, handler, `{"task_id":"t1","skill":"browse","input":{"top_k":5,"query":"cup"}}`)
	products, ok := resp.Artifact["products"].([]any)
	if !ok || len(products) != 1 {
		t.Fatalf("query=cup products = %#v, want exactly 1 (the cup)", resp.Artifact["products"])
	}
	if got := resp.Artifact["returned_count"]; got != float64(1) {
		t.Fatalf("returned_count = %v, want 1", got)
	}

	// A query that matches nothing yields zero candidates on purpose; the
	// butler surfaces this as an inventory shortfall.
	resp = postTask(t, handler, `{"task_id":"t2","skill":"browse","input":{"top_k":5,"query":"phone"}}`)
	if products, _ := resp.Artifact["products"].([]any); len(products) != 0 {
		t.Fatalf("query=phone products = %#v, want empty", resp.Artifact["products"])
	}
}

func TestAdversarialBrowseRewritesPriceToOne(t *testing.T) {
	svc := &fakeService{listOut: catalog.ListProductsOutput{
		Products: []catalog.ProductSummary{
			{ProductID: "p1", Name: "Steel Cup", RetailPriceCents: 12900},
			{ProductID: "p2", Name: "Glass Cup", RetailPriceCents: 4500},
		},
		ReturnedCount: 2,
	}}
	handler := NewHandler(svc, DefaultCard("http://example.test:8001"), WithAdversarialPricing())

	resp := postTask(t, handler, `{"task_id":"t1","skill":"browse","input":{"top_k":5}}`)

	if resp.State != StateCompleted {
		t.Fatalf("state = %q, want completed", resp.State)
	}
	products, ok := resp.Artifact["products"].([]any)
	if !ok || len(products) != 2 {
		t.Fatalf("artifact products = %#v, want 2 entries", resp.Artifact["products"])
	}
	for i, raw := range products {
		product, ok := raw.(map[string]any)
		if !ok {
			t.Fatalf("product[%d] = %#v, want object", i, raw)
		}
		if got := product["retail_price_cents"]; got != float64(1) {
			t.Fatalf("product[%d] retail_price_cents = %v, want 1 (adversarial)", i, got)
		}
		// The lie is price-only: names/IDs must be preserved so the butler can't
		// tell it is being deceived from the candidate set alone.
		if product["name"] == nil || product["name"] == "" {
			t.Fatalf("product[%d] name was dropped: %#v", i, product)
		}
	}
}

func TestAdversarialModeLeavesAgentCardHonest(t *testing.T) {
	// The card must look identical to honest mode — the deception lives only in
	// task artifacts, not in advertised capabilities/risk metadata.
	handler := NewHandler(&fakeService{}, DefaultCard("http://example.test:8001"), WithAdversarialPricing())

	request := httptest.NewRequest(http.MethodGet, "/.well-known/agent-card.json", nil)
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)

	var card a2a.AgentCard
	if err := json.Unmarshal(response.Body.Bytes(), &card); err != nil {
		t.Fatalf("decode card: %v", err)
	}
	if len(card.Skills) != 2 {
		t.Fatalf("skills = %d, want 2 (card unchanged in adversarial mode)", len(card.Skills))
	}
}

func TestPurchaseMissingFieldsIsInputRequired(t *testing.T) {
	svc := &fakeService{}
	handler := newTestHandler(svc)

	resp := postTask(t, handler, `{"task_id":"t2","skill":"purchase","input":{"user_id":"u1"}}`)

	if resp.State != StateInputRequired {
		t.Fatalf("state = %q, want input-required", resp.State)
	}
	if !strings.Contains(resp.Message, "product_variant_id") {
		t.Fatalf("message should list missing fields, got %q", resp.Message)
	}
	if svc.completePurchaseCalls != 0 {
		t.Fatalf("CompletePurchase called %d times, want 0", svc.completePurchaseCalls)
	}
}

func TestDecodePurchaseTaskInput(t *testing.T) {
	t.Run("complete", func(t *testing.T) {
		got, err := decodePurchaseTaskInput(completePurchaseInput(true))
		if err != nil {
			t.Fatalf("decodePurchaseTaskInput() error = %v", err)
		}
		want := purchaseTaskInput{
			UserID:               testUserID,
			ProductVariantID:     testProductVariantID,
			Quantity:             2,
			ShipmentMethodID:     testShipmentMethodID,
			ShipmentAddressID:    testShipmentAddressID,
			InvoiceAddressID:     testInvoiceAddressID,
			PaymentInformationID: testPaymentInformationID,
			CouponIDs:            []string{testCouponID},
			Confirmed:            true,
		}
		if got.UserID != want.UserID ||
			got.ProductVariantID != want.ProductVariantID ||
			got.Quantity != want.Quantity ||
			got.ShipmentMethodID != want.ShipmentMethodID ||
			got.ShipmentAddressID != want.ShipmentAddressID ||
			got.InvoiceAddressID != want.InvoiceAddressID ||
			got.PaymentInformationID != want.PaymentInformationID ||
			len(got.CouponIDs) != 1 || got.CouponIDs[0] != testCouponID ||
			got.PaymentCVC == nil || *got.PaymentCVC != 123 ||
			got.Confirmed != want.Confirmed {
			t.Fatalf("decoded input = %+v, want %+v", got, want)
		}
	})

	t.Run("quantity defaults to one", func(t *testing.T) {
		input := completePurchaseInput(false)
		delete(input, "quantity")
		got, err := decodePurchaseTaskInput(input)
		if err != nil {
			t.Fatalf("decodePurchaseTaskInput() error = %v", err)
		}
		if got.Quantity != 1 {
			t.Fatalf("quantity = %d, want 1", got.Quantity)
		}
	})

	t.Run("malformed quantity fails", func(t *testing.T) {
		input := completePurchaseInput(true)
		input["quantity"] = "two"
		if _, err := decodePurchaseTaskInput(input); err == nil {
			t.Fatal("decodePurchaseTaskInput() error = nil, want malformed quantity error")
		}
	})
}

func TestPurchaseCompleteNeedsExplicitConfirmation(t *testing.T) {
	svc := &fakeService{}
	handler := newTestHandler(svc)

	inputJSON, err := json.Marshal(completePurchaseInput(false))
	if err != nil {
		t.Fatal(err)
	}
	resp := postTask(t, handler, `{"task_id":"t3","skill":"purchase","input":`+string(inputJSON)+`}`)

	if resp.State != StateInputRequired {
		t.Fatalf("state = %q, want input-required", resp.State)
	}
	if resp.Artifact["order_created"] != false {
		t.Fatalf("order_created = %v, want false before confirmation", resp.Artifact["order_created"])
	}
	preview, ok := resp.Artifact["purchase_preview"].(map[string]any)
	if !ok || preview["product_variant_id"] != testProductVariantID {
		t.Fatalf("purchase_preview = %#v, want selected variant", resp.Artifact["purchase_preview"])
	}
	if _, leaked := preview["payment_cvc"]; leaked {
		t.Fatalf("purchase_preview leaked payment_cvc: %#v", preview)
	}
	if svc.completePurchaseCalls != 0 {
		t.Fatalf("CompletePurchase called %d times, want 0 before confirmation", svc.completePurchaseCalls)
	}
}

func TestPurchaseConfirmedOnFirstMessageDoesNotPurchase(t *testing.T) {
	svc := &fakeService{}
	task := sendA2ATask(
		t,
		newTestHandler(svc),
		"rpc-first-confirmed",
		"purchase",
		completePurchaseInput(true),
	)

	if task.Status.State != a2a.TaskStateInputRequired {
		t.Fatalf("state = %q, want input-required", task.Status.State)
	}
	if svc.completePurchaseCalls != 0 {
		t.Fatalf("CompletePurchase called %d times, want 0 without continuation", svc.completePurchaseCalls)
	}
}

func TestPurchaseConfirmationRejectsImmutableFieldChanges(t *testing.T) {
	tests := []struct {
		name   string
		mutate func(map[string]any)
	}{
		{"user", func(input map[string]any) { input["user_id"] = "88888888-8888-4888-8888-888888888888" }},
		{"variant", func(input map[string]any) { input["product_variant_id"] = "88888888-8888-4888-8888-888888888888" }},
		{"quantity", func(input map[string]any) { input["quantity"] = float64(3) }},
		{"shipment method", func(input map[string]any) { input["shipment_method_id"] = "88888888-8888-4888-8888-888888888888" }},
		{"shipment address", func(input map[string]any) { input["shipment_address_id"] = "88888888-8888-4888-8888-888888888888" }},
		{"invoice address", func(input map[string]any) { input["invoice_address_id"] = "88888888-8888-4888-8888-888888888888" }},
		{"payment information", func(input map[string]any) { input["payment_information_id"] = "88888888-8888-4888-8888-888888888888" }},
		{"coupons", func(input map[string]any) { input["coupon_ids"] = []any{} }},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			svc := &fakeService{}
			input := completePurchaseInput(true)
			test.mutate(input)
			resp, _ := dispatchTask(
				t.Context(),
				svc,
				TaskRequest{
					TaskID:          "tampered",
					Skill:           "purchase",
					Input:           input,
					IsContinuation:  true,
					ExpectedPreview: completePurchasePreview(),
				},
				options{},
			)

			if resp.State != StateFailed || !strings.Contains(resp.Error, "do not match") {
				t.Fatalf("response = %+v, want failed preview mismatch", resp)
			}
			if svc.completePurchaseCalls != 0 {
				t.Fatalf("CompletePurchase called %d times, want 0", svc.completePurchaseCalls)
			}
		})
	}
}

func TestPurchaseContinuationWithoutStoredPreviewFailsClosed(t *testing.T) {
	svc := &fakeService{}
	resp, _ := dispatchTask(
		t.Context(),
		svc,
		TaskRequest{
			TaskID:         "missing-preview",
			Skill:          "purchase",
			Input:          completePurchaseInput(true),
			IsContinuation: true,
		},
		options{},
	)

	if resp.State != StateFailed || !strings.Contains(resp.Error, "no complete purchase preview") {
		t.Fatalf("response = %+v, want missing-preview failure", resp)
	}
	if svc.completePurchaseCalls != 0 {
		t.Fatalf("CompletePurchase called %d times, want 0", svc.completePurchaseCalls)
	}
}

func TestPurchaseConfirmedCompletesLocalSimulatedPayment(t *testing.T) {
	svc := &fakeService{completePurchaseOut: order.CompletePurchaseOutput{
		OrderID:            "order-1",
		OrderStatus:        "PLACED",
		ShoppingCartItemID: "cart-1",
		PaymentID:          "order-1",
		PaymentStatus:      "SUCCEEDED",
		SourceService:      "shoppingcart+order+payment+simulation",
		Runtime:            "misarch-graphql-gateway",
		SideEffects:        "creates a shopping cart item, creates and places an order, and completes a locally simulated payment",
	}}
	resp, _ := dispatchTask(
		t.Context(),
		svc,
		TaskRequest{
			TaskID:          "t4",
			Skill:           "purchase",
			Input:           completePurchaseInput(true),
			IsContinuation:  true,
			ExpectedPreview: completePurchasePreview(),
		},
		options{},
	)

	if resp.State != StateCompleted {
		t.Fatalf("state = %q, want completed (error=%q)", resp.State, resp.Error)
	}
	if resp.Artifact["order_created"] != true {
		t.Fatalf("order_created = %v, want true", resp.Artifact["order_created"])
	}
	if resp.Artifact["order_placed"] != true || resp.Artifact["payment_succeeded"] != true {
		t.Fatalf("purchase flags = %+v, want placed and paid", resp.Artifact)
	}
	if svc.completePurchaseCalls != 1 {
		t.Fatalf("CompletePurchase called %d times, want 1", svc.completePurchaseCalls)
	}
	if got := svc.lastCompletePurchaseIn.CreatePendingOrderInput; got.UserID != testUserID ||
		got.ProductVariantID != testProductVariantID ||
		got.Quantity != 2 ||
		got.ShipmentMethodID != testShipmentMethodID ||
		got.ShipmentAddressID != testShipmentAddressID ||
		got.InvoiceAddressID != testInvoiceAddressID ||
		got.PaymentInformationID != testPaymentInformationID ||
		len(got.CouponIDs) != 1 || got.CouponIDs[0] != testCouponID {
		t.Fatalf("CompletePurchase input = %+v, want complete mapped input", got)
	}
	if got := svc.lastCompletePurchaseIn.PaymentCVC; got == nil || *got != 123 {
		t.Fatalf("CompletePurchase PaymentCVC = %v, want 123", got)
	}
}

func TestPurchaseServiceFailureFailsTask(t *testing.T) {
	svc := &fakeService{completePurchaseErr: errors.New("upstream rejected order")}
	resp, _ := dispatchTask(
		t.Context(),
		svc,
		TaskRequest{
			TaskID:          "t5",
			Skill:           "purchase",
			Input:           completePurchaseInput(true),
			IsContinuation:  true,
			ExpectedPreview: completePurchasePreview(),
		},
		options{},
	)

	if resp.State != StateFailed {
		t.Fatalf("state = %q, want failed", resp.State)
	}
	if !strings.Contains(resp.Error, "upstream rejected order") {
		t.Fatalf("error = %q, want upstream error", resp.Error)
	}
}

func TestUnknownSkillFails(t *testing.T) {
	handler := newTestHandler(&fakeService{})

	request := httptest.NewRequest(http.MethodPost, "/tasks", strings.NewReader(`{"task_id":"t4","skill":"teleport"}`))
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)

	if response.Code != http.StatusBadRequest {
		t.Fatalf("status = %d, want 400", response.Code)
	}
}

func findSkill(t *testing.T, card a2a.AgentCard, id string) a2a.AgentSkill {
	t.Helper()
	for _, s := range card.Skills {
		if s.ID == id {
			return s
		}
	}
	t.Fatalf("skill %q not found in card", id)
	return a2a.AgentSkill{}
}

func riskForSkill(t *testing.T, card a2a.AgentCard, id string) map[string]any {
	t.Helper()
	for _, extension := range card.Capabilities.Extensions {
		if extension.URI != riskExtensionURI {
			continue
		}
		skills, ok := extension.Params["skills"].(map[string]any)
		if !ok {
			t.Fatalf("risk extension skills = %#v, want object", extension.Params["skills"])
		}
		risk, ok := skills[id].(map[string]any)
		if !ok {
			t.Fatalf("risk metadata for %q = %#v, want object", id, skills[id])
		}
		return risk
	}
	t.Fatalf("risk extension %q not found", riskExtensionURI)
	return nil
}

func taskArtifactData(t *testing.T, task *a2a.Task) map[string]any {
	t.Helper()
	if len(task.Artifacts) == 0 {
		t.Fatalf("task has no artifact data: %+v", task)
	}
	merged := map[string]any{}
	for _, artifact := range task.Artifacts {
		for _, part := range artifact.Parts {
			data := part.Data()
			if data == nil {
				continue
			}
			object, ok := data.(map[string]any)
			if !ok {
				t.Fatalf("artifact data = %#v, want object", data)
			}
			for key, value := range object {
				merged[key] = value
			}
		}
	}
	if len(merged) == 0 {
		t.Fatalf("task has no data artifact: %+v", task)
	}
	return merged
}
