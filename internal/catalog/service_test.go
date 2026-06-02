package catalog

import (
	"context"
	"errors"
	"reflect"
	"strings"
	"testing"
)

type fakeGraphQLClient struct {
	query     string
	variables map[string]any
	do        func(out any) error
}

func (f *fakeGraphQLClient) Do(
	ctx context.Context,
	query string,
	variables map[string]any,
	out any,
) error {
	f.query = query
	f.variables = variables

	return f.do(out)
}

func TestNormalizeTopKUsesDefault(t *testing.T) {
	got, err := normalizeTopK(0)
	if err != nil {
		t.Fatalf("normalizeTopK() returned error: %v", err)
	}

	if got != 5 {
		t.Fatalf("normalizeTopK() = %d, want 5", got)
	}
}

func TestNormalizeTopKRejectsLargeValue(t *testing.T) {
	_, err := normalizeTopK(11)
	if err == nil {
		t.Fatal("normalizeTopK() returned nil error, want validation error")
	}
}

func TestListProducts(t *testing.T) {
	gql := &fakeGraphQLClient{
		do: func(out any) error {
			response := out.(*listProductsResponse)
			response.Products.Nodes = []productNode{
				{
					ID: "product-1",
					DefaultVariant: &productVariant{
						ID: "variant-1",
						CurrentVersion: &productVersion{
							Name:        "Beginner Telescope",
							RetailPrice: 12900,
						},
					},
					Categories: categoryPage{
						Nodes: []categoryNode{
							{Name: " Optics "},
							{Name: ""},
						},
					},
				},
			}

			return nil
		},
	}

	service := NewService(gql)

	got, err := service.ListProducts(context.Background(), 3)
	if err != nil {
		t.Fatalf("ListProducts() returned error: %v", err)
	}

	want := ListProductsOutput{
		Products: []ProductSummary{
			{
				ProductID:        "product-1",
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
	}

	if !reflect.DeepEqual(got, want) {
		t.Fatalf("ListProducts() = %#v, want %#v", got, want)
	}

	if gql.variables["first"] != 3 {
		t.Fatalf("first variable = %#v, want 3", gql.variables["first"])
	}

	if !strings.Contains(gql.query, "defaultVariant") {
		t.Fatalf("query does not request defaultVariant: %q", gql.query)
	}
}

func TestListProductsPropagatesGraphQLError(t *testing.T) {
	gql := &fakeGraphQLClient{
		do: func(out any) error {
			return errors.New("upstream unavailable")
		},
	}

	service := NewService(gql)

	_, err := service.ListProducts(context.Background(), 3)
	if err == nil {
		t.Fatal("ListProducts() returned nil error, want upstream error")
	}

	if !strings.Contains(err.Error(), "upstream unavailable") {
		t.Fatalf("error = %q, want upstream error", err)
	}
}

func TestMapProductRejectsMissingVariant(t *testing.T) {
	_, err := mapProduct(productNode{
		ID: "product-1",
	})
	if err == nil {
		t.Fatal("mapProduct() returned nil error, want missing variant error")
	}
}

func TestMapProductRejectsMissingCurrentVersion(t *testing.T) {
	_, err := mapProduct(productNode{
		ID:             "product-1",
		DefaultVariant: &productVariant{ID: "variant-1"},
	})
	if err == nil {
		t.Fatal("mapProduct() returned nil error, want missing version error")
	}
}
func TestGetProduct(t *testing.T) {
	const productID = "550e8400-e29b-41d4-a716-446655440000"

	gql := &fakeGraphQLClient{
		do: func(out any) error {
			response := out.(*getProductResponse)
			response.Product = &productNode{
				ID: productID,
				DefaultVariant: &productVariant{
					ID: "variant-1",
					CurrentVersion: &productVersion{
						Name:        "Advanced Telescope",
						Description: "A telescope for clear night skies.",
						RetailPrice: 25900,
					},
				},
				Categories: categoryPage{
					Nodes: []categoryNode{
						{Name: "Optics"},
					},
				},
			}

			return nil
		},
	}

	service := NewService(gql)

	got, err := service.GetProduct(context.Background(), productID)
	if err != nil {
		t.Fatalf("GetProduct() returned error: %v", err)
	}

	if !got.Found {
		t.Fatal("GetProduct() Found = false, want true")
	}

	if got.Product == nil {
		t.Fatal("GetProduct() Product = nil")
	}

	if got.Product.Name != "Advanced Telescope" {
		t.Fatalf("product name = %q", got.Product.Name)
	}

	if gql.variables["id"] != productID {
		t.Fatalf("id variable = %#v, want %q", gql.variables["id"], productID)
	}

	if !strings.Contains(gql.query, "$id: UUID!") {
		t.Fatalf("query does not declare UUID input: %q", gql.query)
	}
}

func TestGetProductRejectsInvalidUUID(t *testing.T) {
	called := false

	gql := &fakeGraphQLClient{
		do: func(out any) error {
			called = true
			return nil
		},
	}

	service := NewService(gql)

	_, err := service.GetProduct(context.Background(), "not-a-uuid")
	if err == nil {
		t.Fatal("GetProduct() returned nil error, want UUID validation error")
	}

	if called {
		t.Fatal("GraphQL client was called for invalid UUID")
	}
}

func TestGetProductHandlesNullProduct(t *testing.T) {
	const productID = "550e8400-e29b-41d4-a716-446655440000"

	gql := &fakeGraphQLClient{
		do: func(out any) error {
			return nil
		},
	}

	service := NewService(gql)

	got, err := service.GetProduct(context.Background(), productID)
	if err != nil {
		t.Fatalf("GetProduct() returned error: %v", err)
	}

	if got.Found {
		t.Fatal("GetProduct() Found = true, want false")
	}

	if got.Product != nil {
		t.Fatalf("GetProduct() Product = %#v, want nil", got.Product)
	}
}
