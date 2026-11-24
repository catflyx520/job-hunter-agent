import * as React from "react"
import { Checkbox as CheckboxPrimitive } from "radix-ui"

import { useInk, useMergedRef } from "@/lib/ink/react"
import { checkboxRecipe } from "@/lib/ink/recipes/checkbox-ink"
import { REVEAL_DASH, REVEAL_WHEN_CHECKED, REVEAL_WHEN_INDETERMINATE, markTouched } from "@/lib/ink/recipes/draw-on-ink"
import { cn } from "@/lib/utils"

function Checkbox({
  className,
  seed,
  disabled,
  ref,
  onClickCapture,
  ...props
}: React.ComponentProps<typeof CheckboxPrimitive.Root> & {
  seed?: string | number
}) {
  const invalid = props["aria-invalid"] === true || props["aria-invalid"] === "true"
  const forced = "data-focus-visible" in props
  const { hostRef, hostProps, node } = useInk({ recipe: checkboxRecipe, params: { disabled: !!disabled, invalid }, kind: "checkbox", seed, layers: forced ? "all" : undefined })
  return (
    <CheckboxPrimitive.Root
      data-slot="checkbox"
      ref={useMergedRef<HTMLButtonElement>(hostRef, ref)}
      {...hostProps}
      disabled={disabled}
      onClickCapture={(e) => {
        markTouched(e)
        onClickCapture?.(e)
      }}
      className={cn(
        "peer relative isolate size-4 shrink-0 after:absolute after:-inset-1.5 disabled:cursor-not-allowed",
        REVEAL_DASH,
        REVEAL_WHEN_CHECKED,
        REVEAL_WHEN_INDETERMINATE,
        "group-hover/field:[&>svg_[data-layer=hover]]:visible group-hover/field:[&>svg_[data-layer=hover]]:opacity-100",
        "has-[+[data-slot=label]:hover]:[&>svg_[data-layer=hover]]:visible has-[+[data-slot=label]:hover]:[&>svg_[data-layer=hover]]:opacity-100",
        "has-[+input+[data-slot=label]:hover]:[&>svg_[data-layer=hover]]:visible has-[+input+[data-slot=label]:hover]:[&>svg_[data-layer=hover]]:opacity-100",
        className
      )}
      {...props}
    >
      {node}
      <CheckboxPrimitive.Indicator
        data-slot="checkbox-indicator"
        className="pointer-events-none absolute inset-0 hidden place-content-center leading-none font-bold forced-colors:grid forced-colors:data-[state=checked]:before:content-['✓'] forced-colors:data-[state=indeterminate]:before:content-['–']"
      />
    </CheckboxPrimitive.Root>
  )
}

export { Checkbox }
