# @label-os/ui

Shared React components for the Label OS design system.

## Adding Components

1. Add the component in `src/components/<component-name>.tsx`.
2. Keep component props typed and framework-agnostic. Components should not import from apps or include product business logic.
3. Accept `className` and merge it with local Tailwind classes using `cn`.
4. Prefer accessible HTML defaults, including native elements, labels, `aria-*` attributes, and semantic regions where appropriate.
5. Add focused tests when the component has variants, accessibility attributes, or meaningful prop behavior.
6. Export the component and its public prop type from `src/index.ts`.

Tailwind classes used in this package are picked up by `apps/web/tailwind.config.ts`.
