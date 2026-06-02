package catalog

type ProductSummary struct {
	ProductID        string   `json:"product_id"`
	VariantID        string   `json:"variant_id"`
	Name             string   `json:"name"`
	RetailPriceCents int      `json:"retail_price_cents"`
	Currency         string   `json:"currency"`
	Categories       []string `json:"categories"`
}

type ListProductsOutput struct {
	Products      []ProductSummary `json:"products"`
	ReturnedCount int              `json:"returned_count"`
	SourceService string           `json:"source_service"`
	Runtime       string           `json:"runtime"`
	SideEffects   string           `json:"side_effects"`
}

type ProductDetail struct {
	ProductID        string   `json:"product_id"`
	VariantID        string   `json:"variant_id"`
	Name             string   `json:"name"`
	Description      string   `json:"description"`
	RetailPriceCents int      `json:"retail_price_cents"`
	Currency         string   `json:"currency"`
	Categories       []string `json:"categories"`
}

type GetProductOutput struct {
	Found         bool           `json:"found"`
	Product       *ProductDetail `json:"product,omitempty"`
	SourceService string         `json:"source_service"`
	Runtime       string         `json:"runtime"`
	SideEffects   string         `json:"side_effects"`
}
