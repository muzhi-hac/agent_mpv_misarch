// Package a2aserver exposes the merchant store-agent through the official A2A
// JSON-RPC protocol. The domain request/response types below are deliberately
// transport-neutral: the A2A executor and the deprecated REST compatibility
// endpoint both adapt them to their respective wire formats.
package a2aserver

// TaskRequest is the internal command decoded from an A2A Message DataPart. It
// also remains the body of the deprecated POST /tasks compatibility endpoint.
type TaskRequest struct {
	TaskID          string         `json:"task_id"`
	Skill           string         `json:"skill"` // must match a Skill.ID
	Input           map[string]any `json:"input"` // skill-specific payload
	IsContinuation  bool           `json:"-"`     // true only for an A2A message referencing a stored task
	ExpectedPreview map[string]any `json:"-"`     // server-owned preview from the stored A2A task
}

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

// TaskState is the legacy experiment-facing state. The A2A executor maps these
// values onto the protocol's TASK_STATE_* lifecycle values.
type TaskState string

const (
	StateWorking       TaskState = "working"
	StateInputRequired TaskState = "input-required"
	StateCompleted     TaskState = "completed"
	StateFailed        TaskState = "failed"
)

// TaskResponse is the transport-neutral result and the response returned by the
// deprecated POST /tasks compatibility endpoint.
type TaskResponse struct {
	TaskID   string         `json:"task_id"`
	State    TaskState      `json:"state"`
	Message  string         `json:"message,omitempty"`  // human-facing note, e.g. missing fields
	Artifact map[string]any `json:"artifact,omitempty"` // final output (products / order)
	Error    string         `json:"error,omitempty"`
}
