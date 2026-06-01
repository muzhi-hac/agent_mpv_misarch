package misarch

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

type Client struct {
	endpoint   string
	httpClient *http.Client
}

type GraphQLRequest struct {
	Query     string         `json:"query"`
	Variables map[string]any `json:"variables,omitempty"`
}
type GraphQLError struct {
	Message string `json:"message"`
}
type GraphQLResponse struct {
	Data   json.RawMessage `json:"data"`
	Errors []GraphQLError  `json:"errors"`
}

func NewClient(endpoint string, timeout time.Duration) *Client {
	return &Client{
		endpoint: endpoint,
		httpClient: &http.Client{
			Timeout: timeout,
		},
	}
}
func (c *Client) Do(
	ctx context.Context,
	query string,
	variables map[string]any,
	out any,
) error {
	body, err := json.Marshal(GraphQLRequest{
		Query:     query,
		Variables: variables,
	})
	if err != nil {
		return fmt.Errorf("marshal graphql request: %w", err)
	}

	request, err := http.NewRequestWithContext(ctx, http.MethodPost, c.endpoint, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("create graphql request: %w", err)
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Accept", "application/json")

	response, err := c.httpClient.Do(request)
	if err != nil {
		return fmt.Errorf("call graphql endpoint: %w", err)
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf(
			"graphql endpoint returned status %d",
			response.StatusCode,
		)
	}
	return decodeResponse(response.Body, out)
}
func decodeResponse(body io.Reader, out any) error {
	var response GraphQLResponse
	if err := json.NewDecoder(body).Decode(&response); err != nil {
		return fmt.Errorf("decode graphql response: %w", err)
	}
	if len(response.Errors) > 0 {
		return fmt.Errorf("graphql error: %s", response.Errors[0].Message)
	}
	if err := json.Unmarshal(response.Data, out); err != nil {
		return fmt.Errorf("decode graphql data: %w", err)
	}
	return nil

}
func (c *Client) Ready(ctx context.Context) error {
	var output struct {
		TypeName string `json:"__typename"`
	}

	return c.Do(
		ctx,
		"query Ready { __typename }",
		nil,
		&output,
	)
}
