"use client"

import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Slot, Toggle as TogglePrimitive } from "radix-ui"

import { useInk, useMergedRef } from "@/lib/ink/react"
import { toggleRecipe, type ToggleTone } from "@/lib/ink/recipes/toggle-ink"
import { cn } from "@/lib/utils"

const toggleVariants = cva(
  "relative isolate inline-flex shrink-0 items-center justify-center gap-2 font-hand font-bold whitespace-nowrap transition-[translate] duration-(--ll-dur-press) ease-out active:translate-y-(--ll-press-sink) [&[data-pressed]:not([data-pressed=false])]:translate-y-(--ll-press-sink) disabled:pointer-events-none disabled:text-pencil-text forced-colors:data-[state=on]:bg-[Highlight] forced-colors:data-[state=on]:text-[HighlightText] [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not(.absolute):not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "",
        outline: "",
      },
      size: {
        default: "h-9 min-w-9 px-2 text-base compact:h-8 compact:min-w-8 calm:h-7 calm:min-w-7",
        sm: "h-8 min-w-8 px-1.5 text-[15px] compact:h-7 compact:min-w-7 calm:h-7 calm:min-w-7",
        lg: "h-10 min-w-10 px-2.5 text-[17px] compact:h-9 compact:min-w-9 calm:h-8 calm:min-w-8",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Toggle({
  className,
  variant,
  size,
  tone,
  seed,
  asChild,
  disabled,
  children,
  ref,
  ...props
}: React.ComponentProps<typeof TogglePrimitive.Root> &
  VariantProps<typeof toggleVariants> & {
    tone?: ToggleTone
    seed?: string | number
  }) {
  const v = variant ?? "default"
  const forced = "data-focus-visible" in props
  const { hostRef, hostProps, node } = useInk({
    recipe: toggleRecipe,
    params: { variant: v, disabled: !!disabled, tone, invalid: props["aria-invalid"] === true || props["aria-invalid"] === "true" },
    kind: "toggle",
    seed,
    layers: forced ? "all" : undefined,
  })
  return (
    <TogglePrimitive.Root
      data-slot="toggle"
      data-variant={v}
      data-size={size ?? "default"}
      data-ink-sink="self"
      ref={useMergedRef<HTMLButtonElement>(hostRef, ref)}
      {...hostProps}
      asChild={asChild}
      disabled={disabled}
      className={cn(toggleVariants({ variant: v, size, className }))}
      {...props}
    >
      {!asChild && node}
      {asChild ? <Slot.Slottable>{children}</Slot.Slottable> : children}
      {asChild && node}
    </TogglePrimitive.Root>
  )
}

export { Toggle, toggleVariants }
