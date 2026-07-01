package a2aserver

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"misarch-agent-gateway-go/internal/catalog"
	"misarch-agent-gateway-go/internal/order"
)

type fakeService struct {
	listOut          catalog.ListProductsOutput
	createOrderCalls int
}

func (f *fakeService) ListProducts(ctx context.Context, topK int) (catalog.ListProductsOutput, error) {
	return f.listOut, nil
}

func (f *fakeService) GetProduct(ctx context.Context, productID string) (catalog.GetProductOutput, error) {
	return catalog.GetProductOutput{Found: true, Product: &catalog.ProductDetail{ProductID: productID}}, nil
}

func (f *fakeService) CreatePendingOrder(ctx context.Context, in order.CreatePendingOrderInput) (order.CreatePendingOrderOutput, error) {
	f.createOrderCalls++
	return order.CreatePendingOrderOutput{OrderID: "should-not-happen"}, nil
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

func TestAgentCardServed(t *testing.T) {
	handler := newTestHandler(&fakeService{})

	request := httptest.NewRequest(http.MethodGet, "/.well-known/agent-card.json", nil)
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", response.Code)
	}

	var card AgentCard
	if err := json.Unmarshal(response.Body.Bytes(), &card); err != nil {
		t.Fatalf("decode card: %v", err)
	}
	if len(card.Skills) != 2 {
		t.Fatalf("skills = %d, want 2", len(card.Skills))
	}

	purchase := findSkill(t, card, "purchase")
	if !purchase.RequiresConfirmation || purchase.RiskLevel != "high" {
		t.Fatalf("purchase skill = %+v, want high risk requiring confirmation", purchase)
	}
	browse := findSkill(t, card, "browse")
	if browse.RequiresConfirmation || browse.RiskLevel != "none" {
		t.Fatalf("browse skill = %+v, want no risk", browse)
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

	var card AgentCard
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
	if svc.createOrderCalls != 0 {
		t.Fatalf("CreatePendingOrder called %d times, want 0 (Phase 1 never creates an order)", svc.createOrderCalls)
	}
}

func TestPurchaseCompleteIsValidatedDryRun(t *testing.T) {
	svc := &fakeService{}
	handler := newTestHandler(svc)

	body := `{"task_id":"t3","skill":"purchase","input":{` +
		`"user_id":"u","product_variant_id":"v","shipment_method_id":"s",` +
		`"shipment_address_id":"sa","invoice_address_id":"ia","payment_information_id":"pi"}}`
	resp := postTask(t, handler, body)

	if resp.State != StateCompleted {
		t.Fatalf("state = %q, want completed", resp.State)
	}
	if resp.Artifact["order_created"] != false {
		t.Fatalf("order_created = %v, want false (Phase 1 dry-run)", resp.Artifact["order_created"])
	}
	if svc.createOrderCalls != 0 {
		t.Fatalf("CreatePendingOrder called %d times, want 0 (Phase 1 never creates an order)", svc.createOrderCalls)
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

func findSkill(t *testing.T, card AgentCard, id string) Skill {
	t.Helper()
	for _, s := range card.Skills {
		if s.ID == id {
			return s
		}
	}
	t.Fatalf("skill %q not found in card", id)
	return Skill{}
}
