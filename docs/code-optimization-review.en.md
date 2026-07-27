# Code Optimization Review — Go Backend

Scope: `internal/a2aserver`, `internal/order`, `internal/catalog`,
`internal/httpserver`, `internal/config`, `internal/misarch`, `cmd/server`.
This is a source read, not a profiler run — findings are ranked by how
concrete and low-risk the fix is, not by guessed impact. This review is
referenced from `docs/cnae-report-v2-overleaf.tex` (Sec. III-D/VII).

Overall: the codebase is in good shape. Errors are wrapped with context,
inputs are validated at the boundary (UUIDs, quantity range, CVC shape),
tests cover the tricky protocol-state paths, and comments explain *why*
rather than restating the code. The findings below are real but narrow.

## 1. Payment attribution race under concurrent purchases (correctness)

`internal/order/service.go`, `waitForPayment` / `paymentIDs`.

`CompletePurchase` identifies "the" new payment for a purchase by snapshotting
existing payment IDs for a `payment_information_id` before placing the order,
then polling until a payment shows up that wasn't in that snapshot:

```go
existingPaymentIDs, err := s.paymentIDs(ctx, input.PaymentInformationID)
...
placed, err := s.placeOrder(ctx, pending.OrderID, input.PaymentCVC)
...
payment, err := s.waitForPayment(ctx, input.PaymentInformationID, existingPaymentIDs)
```

If two purchases run concurrently with the same `payment_information_id`
(same saved card), both snapshots are taken around the same time, and
`waitForPayment`'s scan (`for _, payment := range payments`) has no way to
tell which *new* payment belongs to which order — it just returns the first
unseen one it finds in whatever order the GraphQL response lists them. One
task can end up reporting the other task's payment as its own.

This is already anticipated as a test scenario (`BUY-F15` in
`docs/report-aligned-test-scenarios.zh.md` and Table II of the LaTeX
revision), but the code does not yet implement the "serialize or fail
closed" behavior that scenario expects — there's no lock or per-order
correlation key on the payment side.

**Fix direction:** the cleanest fix is upstream — have MiSArch's `placeOrder`
mutation return (or `PaymentInformationID`'s payment record carry) the order
ID it belongs to, so `waitForPayment` can filter by that instead of "unseen
since snapshot." If that's not available, a short-term mitigation is a
per-`payment_information_id` mutex in `Service` so `CompletePurchase` calls
sharing a payment method are serialized rather than racing.

## 2. `browse` scans the full catalog window on every call

`internal/a2aserver/server.go`, `handleBrowse` + `browseScanLimit = 100`.

MiSArch's GraphQL schema has no text search, so `browse` always fetches
`browseScanLimit` (100) products — each with nested variant, price, and
category data — and filters them in Go, even when the caller only asked for
`top_k: 5`. This is called out honestly in the code comments as an
intentional tradeoff, and it's fine at the catalog's current size, but it's
worth flagging because:

- It's a likely contributor to the MCP/A2A latency overhead the paper's own
  Fig. 1 and Fig. 2 measure (over-fetching on every browse call, not just the
  ones that need a large page).
- The paper's own "Future Work" section calls for a richer catalog — once
  that happens, this becomes an O(catalog size) GraphQL call on every browse,
  not O(top_k).

**Fix direction:** if/when MiSArch's catalog grows, either push search
filtering into the GraphQL query (if MiSArch adds it) or cache the scanned
page for a short TTL (products don't change every second) so repeated
browse calls in one demo/session don't refetch the same 100-product window.

## 3. Upstream HTTP client uses Go's default connection pool size

`internal/misarch/client.go`, `NewClient`.

The GraphQL client is constructed once and reused correctly (this is good —
no per-request `http.Client` allocation, and `PasswordTokenSource` caches
its token with a 30s expiry skew under a mutex). But `NewClient` doesn't set
a custom `Transport`, so it inherits `http.DefaultTransport`'s
`MaxIdleConnsPerHost: 2`. Since every request — from all four experimental
arms, the four-pane live demo, and the regression scripts — ultimately funnels
through this one `Client` to one upstream host, concurrent load (e.g. the
four-arm broadcast demo, or `go test ./... -race` hitting a real backend)
can hit connection churn instead of reusing keep-alive connections.

**Fix direction:** give `NewClient` a `Transport` with a higher
`MaxIdleConnsPerHost` (e.g. 32–64) for the single upstream host. Low risk,
one-line change, directly helps the concurrency scenarios the paper and the
negative-path matrix already care about.

## 4. `joinFields` reimplements `strings.Join`

`internal/a2aserver/server.go:444-453`:

```go
func joinFields(fields []string) string {
	out := ""
	for i, f := range fields {
		if i > 0 {
			out += ", "
		}
		out += f
	}
	return out
}
```

This is exactly `strings.Join(fields, ", ")`. Trivial, but worth deleting —
one fewer hand-rolled helper to maintain, and `strings.Join` is O(n) via a
single builder instead of repeated string concatenation.

## 5. (Low priority, style only) Preview-equality via double JSON round-trip

`internal/a2aserver/server.go`, `decodePurchaseTaskInput` /
`samePurchasePreview` marshal the input `map[string]any` to JSON and
unmarshal it into `purchaseTaskInput` twice (once for "expected", once for
"actual") just to compare typed fields. It's correct and the payloads are
small (a handful of UUIDs + an int), so this isn't worth optimizing for
speed — but a direct field-by-field comparison over the decoded struct
would be marginally simpler to read. Not worth doing on its own; bundle it
if `samePurchasePreview` is touched for another reason.

## What's already solid (no action needed)

- `internal/order/service.go` and `internal/catalog/service.go`: consistent
  input validation at the boundary, wrapped errors with operation context,
  no silent failure paths.
- `internal/httpserver/server.go`: CORS handling correctly distinguishes
  preflight `OPTIONS` rejection from same-origin passthrough, and only wraps
  the mux in CORS middleware when origins are actually configured.
- `internal/misarch/auth.go`: token caching is correctly mutex-guarded and
  expiry uses a 30s skew (falls back to half the token lifetime for very
  short-lived tokens) — no thundering-herd re-auth risk under the current
  design.
- `internal/a2aserver/executor.go`: the A2A executor cleanly adapts the
  official SDK's task lifecycle to the existing `dispatchTask` domain logic
  without duplicating skill routing between the executor and the deprecated
  `/tasks` REST shim.
