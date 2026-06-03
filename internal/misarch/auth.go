package misarch

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"
)

type PasswordTokenSource struct {
	tokenURL string
	clientID string
	username string
	password string

	httpClient *http.Client
	now        func() time.Time

	mu          sync.Mutex
	cachedToken string
	expiresAt   time.Time
}

type tokenEndpointResponse struct {
	AccessToken string `json:"access_token"`
	TokenType   string `json:"token_type"`
	ExpiresIn   int    `json:"expires_in"`
}

func NewPasswordTokenSource(
	tokenURL string,
	clientID string,
	username string,
	password string,
	timeout time.Duration,
) *PasswordTokenSource {
	return &PasswordTokenSource{
		tokenURL: tokenURL,
		clientID: clientID,
		username: username,
		password: password,
		httpClient: &http.Client{
			Timeout: timeout,
		},
		now: time.Now,
	}
}

func (s *PasswordTokenSource) Token(ctx context.Context) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if s.cachedToken != "" && s.now().Before(s.expiresAt) {
		return s.cachedToken, nil
	}

	token, expiresAt, err := s.fetchToken(ctx)
	if err != nil {
		return "", err
	}

	s.cachedToken = token
	s.expiresAt = expiresAt

	return token, nil
}

func (s *PasswordTokenSource) fetchToken(ctx context.Context) (string, time.Time, error) {
	form := url.Values{}
	form.Set("grant_type", "password")
	form.Set("client_id", s.clientID)
	form.Set("username", s.username)
	form.Set("password", s.password)

	request, err := http.NewRequestWithContext(ctx, http.MethodPost, s.tokenURL, strings.NewReader(form.Encode()))
	if err != nil {
		return "", time.Time{}, fmt.Errorf("create token request: %w", err)
	}
	request.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	request.Header.Set("Accept", "application/json")

	response, err := s.httpClient.Do(request)
	if err != nil {
		return "", time.Time{}, fmt.Errorf("call token endpoint: %w", err)
	}
	defer response.Body.Close()

	if response.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(response.Body, 4096))
		return "", time.Time{}, fmt.Errorf("token endpoint returned status %d: %s", response.StatusCode, string(body))
	}

	var decoded tokenEndpointResponse
	if err := json.NewDecoder(response.Body).Decode(&decoded); err != nil {
		return "", time.Time{}, fmt.Errorf("decode token response: %w", err)
	}
	if decoded.AccessToken == "" {
		return "", time.Time{}, fmt.Errorf("token response did not include access_token")
	}

	return decoded.AccessToken, tokenExpiry(s.now(), decoded.ExpiresIn), nil
}

func tokenExpiry(now time.Time, expiresIn int) time.Time {
	if expiresIn <= 0 {
		return now.Add(time.Minute)
	}

	lifetime := time.Duration(expiresIn) * time.Second
	skew := 30 * time.Second
	if lifetime <= 2*skew {
		skew = lifetime / 2
	}

	return now.Add(lifetime - skew)
}
