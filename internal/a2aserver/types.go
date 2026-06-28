// Package a2aserver is a thin A2A (agent-to-agent) shell over the existing
// catalog and order services. It exposes a merchant "store-agent" with two
// coarse-grained skills — browse and purchase — discoverable via an Agent Card,
// and dispatched over a simplified REST-style task endpoint.
//
// This is a deliberately minimal subset of the A2A architecture (not the full
// JSON-RPC 2.0 wire protocol): it validates the architectural pattern — separate
// trust domains, Agent Card capability discovery, explicit risk metadata — rather
// than wire-level interoperability with production A2A agents.
package a2aserver

// AgentCard is served at GET /.well-known/agent-card.json.
type AgentCard struct {
	Name         string  `json:"name"`
	Version      string  `json:"version"`
	Description  string  `json:"description"`
	Endpoint     string  `json:"endpoint"` // base URL; tasks are posted to {endpoint}/tasks
	Skills       []Skill `json:"skills"`
	Capabilities struct {
		Streaming bool `json:"streaming"` // false for now
	} `json:"capabilities"`
	Auth struct {
		Schemes []string `json:"schemes"` // e.g. ["none"] for the demo
	} `json:"auth"`
}

// Skill is a coarse-grained capability with explicit risk metadata. The risk
// fields let the user-side butler decide whether to enforce confirmation before
// invoking the skill — keeping the confirmation responsibility on the user side.
type Skill struct {
	ID                   string `json:"id"`          // "browse" | "purchase"
	Description          string `json:"description"`
	RiskLevel            string `json:"risk_level"`  // "none" | "low" | "medium" | "high"
	SideEffects          bool   `json:"side_effects"`
	RequiresConfirmation bool   `json:"requires_confirmation"`
}

// TaskRequest is the body of POST /tasks.
type TaskRequest struct {
	TaskID string         `json:"task_id"`
	Skill  string         `json:"skill"` // must match a Skill.ID
	Input  map[string]any `json:"input"` // skill-specific payload
}

// TaskState mirrors the A2A lifecycle (minimal subset).
type TaskState string

const (
	StateWorking       TaskState = "working"
	StateInputRequired TaskState = "input-required"
	StateCompleted     TaskState = "completed"
	StateFailed        TaskState = "failed"
)

// TaskResponse is returned by POST /tasks.
type TaskResponse struct {
	TaskID   string         `json:"task_id"`
	State    TaskState      `json:"state"`
	Message  string         `json:"message,omitempty"`  // human-facing note, e.g. missing fields
	Artifact map[string]any `json:"artifact,omitempty"` // final output (products / order)
	Error    string         `json:"error,omitempty"`
}
