package catalog

import (
	"context"
	"fmt"
	"strings"

	"github.com/google/uuid"
)

const (
	sourceService = "catalog"
	runtimeName   = "misarch-graphql-gateway"
	sideEffects   = "none (read-only)"
	currency      = "EUR"
	defaultTopK   = 5
	maxTopK       = 10
)

const listProductsQuery = `
query ListProducts($first: Int!) {
  products(first: $first) {
    nodes {
      id
      defaultVariant {
        id
        currentVersion {
          name
          retailPrice
        }
      }
      categories(first: 10) {
        nodes {
          name
        }
      }
    }
  }
}`
const getProductQuery = `query GetProduct($id: UUID!) {
  product(id: $id) {
    id
    defaultVariant {
      id
      currentVersion {
        name
        description
        retailPrice
      }
    }
    categories(first: 10) {
      nodes {
        name
      }
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
	gql GraphQLClient
}

type getProductResponse struct {
	Product *productNode `json:"product"`
}
type listProductsResponse struct {
	Products struct {
		Nodes []productNode `json:"nodes"`
	} `json:"products"`
}
type productNode struct {
	ID             string          `json:"id"`
	DefaultVariant *productVariant `json:"defaultVariant"`
	Categories     categoryPage    `json:"categories"`
}

type productVariant struct {
	ID             string          `json:"id"`
	CurrentVersion *productVersion `json:"currentVersion"`
}

type productVersion struct {
	Name        string `json:"name"`
	RetailPrice int    `json:"retailPrice"`
	Description string `json:"description"`
}

type categoryPage struct {
	Nodes []categoryNode `json:"nodes"`
}

type categoryNode struct {
	Name string `json:"name"`
}

func NewService(gql GraphQLClient) *Service {
	return &Service{
		gql: gql,
	}
}

func (s *Service) ListProducts(
	ctx context.Context,
	topK int,
) (ListProductsOutput, error) {
	topK, err := normalizeTopK(topK)
	if err != nil {
		return ListProductsOutput{}, err
	}
	var response listProductsResponse
	err = s.gql.Do(ctx, listProductsQuery, map[string]any{"first": topK}, &response)
	if err != nil {
		return ListProductsOutput{}, fmt.Errorf("list products: %w", err)
	}
	products := make([]ProductSummary, 0, len(response.Products.Nodes))
	for _, node := range response.Products.Nodes {
		product, err := mapProduct(node)
		if err != nil {
			return ListProductsOutput{}, fmt.Errorf(
				"map product %q: %w",
				node.ID,
				err,
			)
		}

		products = append(products, product)
	}
	return ListProductsOutput{
		Products:      products,
		ReturnedCount: len(products),
		SourceService: sourceService,
		Runtime:       runtimeName,
		SideEffects:   sideEffects,
	}, nil
}
func (s *Service) GetProduct(
	ctx context.Context,
	productID string,
) (GetProductOutput, error) {
	if err := validateProductID(productID); err != nil {
		return GetProductOutput{}, err
	}

	var response getProductResponse
	err := s.gql.Do(
		ctx,
		getProductQuery,
		map[string]any{"id": productID},
		&response,
	)
	if err != nil {
		return GetProductOutput{}, fmt.Errorf(
			"get product %q: %w",
			productID,
			err,
		)
	}

	output := GetProductOutput{
		Found:         false,
		SourceService: sourceService,
		Runtime:       runtimeName,
		SideEffects:   sideEffects,
	}

	if response.Product == nil {
		return output, nil
	}

	detail, err := mapProductDetail(*response.Product)
	if err != nil {
		return GetProductOutput{}, fmt.Errorf(
			"map product %q: %w",
			productID,
			err,
		)
	}

	output.Found = true
	output.Product = &detail

	return output, nil
}

func normalizeTopK(topK int) (int, error) {
	if topK == 0 {
		return defaultTopK, nil
	}

	if topK < 0 || topK > maxTopK {
		return 0, fmt.Errorf(
			"top_k must be between 1 and %d, got %d",
			maxTopK,
			topK,
		)
	}

	return topK, nil
}

func validateProductID(productID string) error {
	if err := uuid.Validate(productID); err != nil {
		return fmt.Errorf(
			"product_id must be a valid UUID: %q: %w",
			productID,
			err,
		)
	}

	return nil
}

func mapProductDetail(node productNode) (ProductDetail, error) {
	summary, err := mapProduct(node)
	if err != nil {
		return ProductDetail{}, err
	}

	return ProductDetail{
		ProductID:        summary.ProductID,
		VariantID:        summary.VariantID,
		Name:             summary.Name,
		Description:      node.DefaultVariant.CurrentVersion.Description,
		RetailPriceCents: summary.RetailPriceCents,
		Currency:         summary.Currency,
		Categories:       summary.Categories,
	}, nil
}

func mapProduct(node productNode) (ProductSummary, error) {
	if strings.TrimSpace(node.ID) == "" {
		return ProductSummary{}, fmt.Errorf("product id is empty")
	}

	if node.DefaultVariant == nil {
		return ProductSummary{}, fmt.Errorf("default variant is missing")
	}

	if node.DefaultVariant.CurrentVersion == nil {
		return ProductSummary{}, fmt.Errorf("current variant version is missing")
	}

	version := node.DefaultVariant.CurrentVersion

	return ProductSummary{
		ProductID:        node.ID,
		VariantID:        node.DefaultVariant.ID,
		Name:             version.Name,
		RetailPriceCents: version.RetailPrice,
		Currency:         currency,
		Categories:       categoryNames(node.Categories),
	}, nil
}

func categoryNames(page categoryPage) []string {
	names := make([]string, 0, len(page.Nodes))

	for _, node := range page.Nodes {
		name := strings.TrimSpace(node.Name)
		if name != "" {
			names = append(names, name)
		}
	}

	return names
}
