# Task 3: Contained Positions Table Actions

## Changes

- Assigned widths to the seven main position columns (980px total) and made the 200px action column fixed to the right, with `Table` horizontal scrolling at 1180px.
- Added `positions-page-header`, `positions-filter-bar`, and `positions-table` classes plus wrapping, width containment, and fixed-column surface styling.
- Added an integration-level Positions table test that renders the real Ant Design table, confirms the framework's fixed-right header class, and checks its local horizontal-overflow behavior.
- Replaced the deprecated Ant Design `destroyOnClose` and Drawer `width` props with their behavior-equivalent `destroyOnHidden` and `size` props.

## RED evidence

Command:

```powershell
npm test -- --run src/pages/Positions/List.test.tsx
```

Result before the implementation: exit 1. The test failed at the action header because it only had `ant-table-cell`, not a fixed-column class. This established that the existing table did not fix the action column or configure the required horizontal scrolling.

The installed Ant Design 6 release uses `ant-table-cell-fix-end` for `fixed: 'right'`, rather than the legacy `ant-table-cell-fix-right` class in the original brief. The final test asserts the current framework class, so it verifies actual Ant Design behavior rather than a project-specific class.

## GREEN evidence

```powershell
npm test -- --run src/pages/Positions/List.test.tsx
# 1 test passed, no warnings

npm test -- --run
# 2 test files passed, 5 tests passed, no warnings

npx eslint src/pages/Positions/List.test.tsx
# exit 0

npm run build
# exit 0: tsc -b && vite build
```

The build emits Vite's standard large-chunk advisory for the existing 4.5MB bundle, but completes successfully.

## Focused lint baseline

`npx eslint src/pages/Positions/List.tsx src/pages/Positions/List.test.tsx` still exits 1 because of the known pre-existing `List.tsx` baseline: 17 errors and 1 hook-dependency warning (unused imports/catch bindings and existing `any` annotations). The new test file has no lint findings, and none of the reported lines are part of this task's changes.

## Test-environment noise

Ant Design checks pseudo-elements during table layout, while JSDOM reports that `getComputedStyle` overload as unimplemented. The test now narrowly delegates pseudo-element calls to the normal element style computation and restores the spy after each test. This keeps the real table rendering path under test without globally silencing console output. The deprecated Ant props were also updated at their source.

## Preservation check

The existing action render callback, status visibility conditions, request callbacks, filters, pagination, row key, and selection configuration remain unchanged.
