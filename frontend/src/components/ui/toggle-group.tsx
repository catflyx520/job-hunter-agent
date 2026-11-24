import * as React from "react"
import { type VariantProps } from "class-variance-authority"
import { Slot, ToggleGroup as ToggleGroupPrimitive } from "radix-ui"

import { toggleVariants } from "@/components/ui/toggle"
import { useInk, useMergedRef } from "@/lib/ink/react"
import { toggleGroupRecipe } from "@/lib/ink/recipes/toggle-group-ink"
import { toggleRecipe, type ToggleTone } from "@/lib/ink/recipes/toggle-ink"
import { cn } from "@/lib/utils"

const ToggleGroupContext = React.createContext<
  VariantProps<typeof toggleVariants> & {
    spacing?: number
    tone?: ToggleTone
    vertical?: boolean
    disabled?: boolean
    invalid?: boolean
  }
>({
  size: "default",
  variant: "default",
  spacing: 0,
})

function ToggleGroup({
  className,
  variant,
  size,
  spacing = 0,
  tone,
  seed,
  disabled,
  orientation,
  children,
  ref,
  ...props
}: React.ComponentProps<typeof ToggleGroupPrimitive.Root> &
  VariantProps<typeof toggleVariants> & {
    spacing?: number
    tone?: ToggleTone
    seed?: string | number
  }) {
  const joinedOutline = spacing === 0 && (variant === "outline" || !!disabled)
  const invalid = !disabled && (props["aria-invalid"] === true || props["aria-invalid"] === "true")
  const { hostRef, hostProps, node } = useInk({
    recipe: toggleGroupRecipe,
    params: { joined: joinedOutline, disabled: !!disabled, invalid },
    kind: "toggle-group",
    seed,
  })
  const ctx = React.useMemo(
    () => ({ variant, size, spacing, tone, vertical: orientation === "vertical", disabled: !!disabled, invalid }),
    [variant, size, spacing, tone, orientation, disabled, invalid]
  )
  return (
    <ToggleGroupPrimitive.Root
      data-slot="toggle-group"
      data-variant={variant}
      data-size={size}
      data-spacing={spacing}
      style={{ "--gap": spacing } as React.CSSProperties}
      ref={useMergedRef<HTMLDivElement>(hostRef, ref)}
      {...hostProps}
      disabled={disabled}
      orientation={orientation}
      className={cn(
        "group/toggle-group relative isolate flex w-fit items-center gap-[--spacing(var(--gap))] data-[orientation=vertical]:flex-col data-[orientation=vertical]:items-stretch",
        className
      )}
      {...(props as React.ComponentProps<typeof ToggleGroupPrimitive.Root>)}
    >
      {node}
      <ToggleGroupContext.Provider value={ctx}>{children}</ToggleGroupContext.Provider>
    </ToggleGroupPrimitive.Root>
  )
}

function ToggleGroupItem({
  className,
  children,
  variant,
  size,
  seed,
  asChild,
  disabled,
  ref,
  ...props
}: React.ComponentProps<typeof ToggleGroupPrimitive.Item> &
  VariantProps<typeof toggleVariants> & {
    seed?: string | number
  }) {
  const context = React.useContext(ToggleGroupContext)
  const v = context.variant || variant || "default"
  const s = context.size || size || "default"
  const joined = context.spacing === 0 && (v !== "outline" || context.variant === "outline")
  const forced = "data-focus-visible" in props
  const own = props["aria-invalid"]
  const invalid = own === undefined ? !!context.invalid : own === true || own === "true"
  const { hostRef, hostProps, node } = useInk({
    recipe: toggleRecipe,
    params: { variant: v, disabled: !!disabled || !!context.disabled, tone: context.tone, joined, vertical: context.vertical, invalid },
    kind: "toggle",
    seed,
    layers: forced ? "all" : undefined,
  })
  return (
    <ToggleGroupPrimitive.Item
      data-slot="toggle-group-item"
      data-variant={v}
      data-size={s}
      data-spacing={context.spacing}
      data-ink-sink="self"
      ref={useMergedRef<HTMLButtonElement>(hostRef, ref)}
      {...hostProps}
      asChild={asChild}
      disabled={disabled}
      className={cn(
        toggleVariants({ variant: v, size: s }),
        "w-auto min-w-0 shrink-0 px-3 focus:z-10 focus-visible:z-10",
        "data-[spacing=0]:first-of-type:[&>svg_[data-part=seam]]:hidden",
        className
      )}
      {...props}
    >
      {!asChild && node}
      {asChild ? <Slot.Slottable>{children}</Slot.Slottable> : children}
      {asChild && node}
    </ToggleGroupPrimitive.Item>
  )
}

export { ToggleGroup, ToggleGroupItem }
