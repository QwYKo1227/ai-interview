# Public Department Review Submit Design

## Context

The public department review page submits an assessment through a one-time public token. A successful submission revokes that token on the backend. The frontend currently calls the review GET endpoint again after the successful POST, so the follow-up request necessarily returns `404 Public resource not found` and displays a misleading error even though the review was saved.

The page also presents recommendation choices with inconsistent visual treatment: “推荐” has a green border, while “不推荐” and “待定” do not have corresponding red and yellow borders.

## Scope

This change is limited to the public department review page and its frontend regression tests. The backend's one-time-token revocation behavior and API contract remain unchanged.

## Design

After a successful review submission, the page will transition to its existing completed-review result view using local component state. It will not call the GET endpoint again with the revoked token. Failed submissions will keep the form visible and continue to display the backend error.

The three recommendation buttons will use a fixed semantic color mapping in both selected and unselected states:

- 推荐: green (`#52c41a`)
- 不推荐: red (`#ff4d4f`)
- 待定: yellow (`#faad14`)

Each button will always show its semantic border color. Selection will additionally apply the corresponding filled emphasis while preserving readable text contrast.

## Data Flow

1. The initial GET resolves the public token and loads the review form.
2. The reviewer selects scores, a recommendation, and an optional comment.
3. The POST submits the review and the backend commits it, revokes the public token, and returns success.
4. The frontend marks the review complete locally and renders the success result without another network request.
5. If the POST fails, local completion state is not changed.

## Testing

Frontend tests will cover these behaviors:

- After a successful POST, the page displays the completed-review result and does not issue a second GET.
- The recommendation buttons expose green, red, and yellow borders respectively.
- Existing submission validation and error behavior remain unchanged unless directly affected by the new test setup.

## Non-goals

- Changing public-token lifetime or revocation semantics.
- Changing backend review submission schemas or responses.
- Redesigning the rest of the public review page.
