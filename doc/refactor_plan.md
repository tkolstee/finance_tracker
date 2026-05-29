# Multi-Account Refactor Plan

## Goal

Create a cleaner separation between business logic and UI by migrating account/filter/transfer logic from `static/js/app.js` into the Python API, while preserving the existing frontend behavior and minimizing user disruption.

This plan is written as a start-from-scratch roadmap for an incremental refactor rather than a full rewrite.

## Why refactor instead of rebuild

- The current app already has a working data model and UI flow.
- The problem is primarily architectural drift and duplicated business logic across JS views.
- Rebuilding from scratch would be much larger and require re-implementing existing behavior, edge cases, and editing workflows.
- A refactor lets us preserve current functionality and migrate logic safely in stages.

## Key principles

1. **API-first business rules**
   - The backend should own account selection, transfer visibility, and totals logic.
   - The frontend should consume prepared view data, not re-derive the same business rules.

2. **Minimal UI logic**
   - JS remains responsible for rendering, user interactions, sorting, and local view state.
   - JS should not duplicate transfer/account filtering logic already handled by the API.

3. **Incremental migration**
   - Add new backend query/view endpoints first.
   - Point existing frontend code at the new endpoints gradually.
   - Keep the current UI working while moving logic behind the scenes.

4. **One source of truth**
   - Transfer collapse rules, account visibility, and net calculations should be implemented in one place.
   - This avoids inconsistent bugs between monthly, template, and all-transactions views.

## Candidate refactor phases

### Phase 1: Audit & identify shared logic

- Catalog existing logic in `static/js/app.js` related to:
  - account selection / visibility
  - transfer collapse and display rules
  - monthly income/expense/transfer section totals
  - template filtering / net totals
  - push-to-template matching
- Document current API capabilities and gaps.

### Phase 2: Add backend query endpoints

Add API endpoints that return frontend-ready data for common views.

Suggested endpoints:

- `GET /api/months/<month>/transactions?account_ids=...`
  - returns month rows with transfer collapse applied according to selected accounts
  - includes `display_payee` / `display_category` semantics if needed
- `GET /api/months/<month>/summary?account_ids=...`
  - returns estimated/actual/reconciled section totals and transfer totals for the selected accounts
- `GET /api/templates?account_ids=...`
  - returns templates visible to the selected accounts
  - returns template section totals and net values
- `GET /api/accounts` (already exists)
  - unchanged, but used as source data for selectors

### Phase 3: Backend transfer/account rules

Implement shared logic in Python for:

- `matchesSelectedAccounts(account_id, transfer_account_id)`
- transfer grouping and collapse behavior
- selecting the correct row in a transfer group when only one account is visible
- net calculation rules:
  - when both transfer accounts are visible, internal transfers cancel in combined net
  - when one side is hidden, the visible side counts toward that account net
- template visibility and totals for transfer templates

### Phase 4: Frontend query adaptation

- Replace in-JS filtering logic with API calls that include account selection.
- Maintain current UI behaviors while reducing duplicated logic.
- Keep sort state local, but request the appropriate dataset from the API.

### Phase 5: Validate & remove duplication

- Run through monthly/template/all views and compare against old behavior.
- Remove redundant JS helpers once the backend handles the same rules.
- Keep behavior consistent across all views.

### Phase 6: Cleanup and documentation

- Document the new API contract and expected query semantics.
- Reduce `static/js/app.js` business-logic code to UI-only helpers.
- Add regression tests for backend business logic, if feasible.

## Expected benefits

- fewer cross-view bugs
- consistent transfer handling across monthly/template/all views
- easier future maintenance
- simpler frontend code
- more robust API for future clients

## Risks and tradeoffs

- frontend/backend split requires careful coordination
- some UI-specific behavior may still remain in JS (sorting, inline editing, ghost rows)
- endpoint proliferation if not designed cleanly
- performance should be monitored, but the app is small enough that server-side filtering is acceptable

## Suggested implementation strategy

1. Start with a small API surface that mirrors current view needs.
2. Keep the existing frontend rendering intact while gradually switching the data source.
3. Validate each step against existing UI behavior.
4. Once backend returns the same shape and totals, remove the duplicated JS logic.

## Conclusion

This should be treated as a refactor-first project. Build the backend view layer and migrate business logic there, then simplify the frontend to a UI/query layer. That will give the best balance of risk, maintainability, and delivery speed.
