package a2aserver

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"iter"

	"github.com/a2aproject/a2a-go/v2/a2a"
	"github.com/a2aproject/a2a-go/v2/a2asrv"
)

// storeAgentExecutor adapts official A2A messages and task lifecycle events to
// the store's existing browse/purchase domain operations.
type storeAgentExecutor struct {
	service Service
	options options
}

func (e *storeAgentExecutor) Execute(
	ctx context.Context,
	execCtx *a2asrv.ExecutorContext,
) iter.Seq2[a2a.Event, error] {
	return func(yield func(a2a.Event, error) bool) {
		if execCtx.StoredTask == nil {
			if !yield(a2a.NewSubmittedTask(execCtx, execCtx.Message), nil) {
				return
			}
		}

		req, err := taskRequestFromMessage(execCtx.Message)
		var resp TaskResponse
		if err != nil {
			resp = TaskResponse{
				TaskID: string(execCtx.TaskID),
				State:  StateFailed,
				Error:  err.Error(),
			}
		} else {
			req.TaskID = string(execCtx.TaskID)
			req.IsContinuation = execCtx.StoredTask != nil
			req.ExpectedPreview = storedPurchasePreview(execCtx.StoredTask)
			resp, _ = dispatchTask(ctx, e.service, req, e.options)
		}

		if resp.Artifact != nil {
			artifact, err := jsonCompatible(resp.Artifact)
			if err != nil {
				resp = TaskResponse{
					TaskID: string(execCtx.TaskID),
					State:  StateFailed,
					Error:  fmt.Sprintf("encode task artifact: %v", err),
				}
			} else if !yield(a2a.NewArtifactEvent(execCtx, a2a.NewDataPart(artifact)), nil) {
				return
			}
		}

		var statusMessage *a2a.Message
		switch {
		case resp.Error != "":
			statusMessage = a2a.NewMessage(a2a.MessageRoleAgent, a2a.NewTextPart(resp.Error))
		case resp.Message != "":
			statusMessage = a2a.NewMessage(a2a.MessageRoleAgent, a2a.NewTextPart(resp.Message))
		}
		yield(a2a.NewStatusUpdateEvent(execCtx, protocolTaskState(resp.State), statusMessage), nil)
	}
}

// storedPurchasePreview reads only server-produced artifacts from the stored
// task. A caller cannot inject this value through the new message payload.
func storedPurchasePreview(task *a2a.Task) map[string]any {
	if task == nil {
		return nil
	}
	for i := len(task.Artifacts) - 1; i >= 0; i-- {
		artifact := task.Artifacts[i]
		if artifact == nil {
			continue
		}
		for _, part := range artifact.Parts {
			if part == nil {
				continue
			}
			data, ok := part.Data().(map[string]any)
			if !ok {
				continue
			}
			if preview, ok := data["purchase_preview"].(map[string]any); ok {
				return preview
			}
		}
	}
	return nil
}

func (*storeAgentExecutor) Cancel(
	_ context.Context,
	execCtx *a2asrv.ExecutorContext,
) iter.Seq2[a2a.Event, error] {
	return func(yield func(a2a.Event, error) bool) {
		yield(a2a.NewStatusUpdateEvent(execCtx, a2a.TaskStateCanceled, nil), nil)
	}
}

func taskRequestFromMessage(message *a2a.Message) (TaskRequest, error) {
	if message == nil {
		return TaskRequest{}, errors.New("A2A message is required")
	}

	for _, part := range message.Parts {
		if part == nil {
			continue
		}
		if data := part.Data(); data != nil {
			return decodeTaskData(data)
		}
		if text := part.Text(); text != "" {
			var req TaskRequest
			if err := json.Unmarshal([]byte(text), &req); err != nil {
				return TaskRequest{}, fmt.Errorf("invalid JSON text part: %w", err)
			}
			if req.Skill == "" {
				return TaskRequest{}, errors.New("A2A message data must include skill")
			}
			return req, nil
		}
	}
	return TaskRequest{}, errors.New("A2A message must contain a structured data part")
}

func decodeTaskData(data any) (TaskRequest, error) {
	encoded, err := json.Marshal(data)
	if err != nil {
		return TaskRequest{}, fmt.Errorf("encode A2A data part: %w", err)
	}

	var payload struct {
		Skill string         `json:"skill"`
		Input map[string]any `json:"input"`
	}
	if err := json.Unmarshal(encoded, &payload); err != nil {
		return TaskRequest{}, fmt.Errorf("decode A2A data part: %w", err)
	}
	if payload.Skill == "" {
		return TaskRequest{}, errors.New("A2A message data must include skill")
	}
	return TaskRequest{Skill: payload.Skill, Input: payload.Input}, nil
}

// The SDK's in-memory task store clones events through gob. Domain structs held
// behind interface{} are not registered with that store, so normalize artifacts
// to JSON-native maps/slices before handing them to an A2A DataPart.
func jsonCompatible(value any) (any, error) {
	encoded, err := json.Marshal(value)
	if err != nil {
		return nil, err
	}
	var normalized any
	if err := json.Unmarshal(encoded, &normalized); err != nil {
		return nil, err
	}
	return normalized, nil
}

func protocolTaskState(state TaskState) a2a.TaskState {
	switch state {
	case StateCompleted:
		return a2a.TaskStateCompleted
	case StateInputRequired:
		return a2a.TaskStateInputRequired
	case StateWorking:
		return a2a.TaskStateWorking
	default:
		return a2a.TaskStateFailed
	}
}
