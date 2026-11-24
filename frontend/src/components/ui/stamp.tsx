"use client"

import * as React from "react"

import { cn } from "@/lib/utils"
import { useEnsureInkDefs } from "@/lib/ink/react"
import { stickers } from "@/lib/ink/art/stickers"
import { memo, stamp } from "@/lib/ink/art-draw"
import type { StampGen, StickerDef } from "@/lib/ink/art/types"

function Stamp({
  name,
  text,
  shape,
  ink,
  sub,
  ring,
  w,
  h,
  size,
  tilt,
  ghost,
  dashed,
  seed,
  label,
  className,
  style,
  ...props
}: Omit<React.ComponentProps<"svg">, "name" | "children" | "viewBox"> & {
  name?: string
  text?: string
  shape?: StampGen["shape"]
  ink?: StampGen["ink"]
  sub?: string
  ring?: string
  w?: number
  h?: number
  size?: number
  tilt?: number
  ghost?: boolean
  dashed?: boolean
  seed?: string | number
  label?: string
}) {
  useEnsureInkDefs()
  const preset = name ? ((stickers as Record<string, StickerDef>)[name] as StampGen | undefined) : undefined
  const p = preset && "gen" in preset && preset.gen === "stamp" ? preset : undefined
  const t = text ?? p?.text
  if (!t) return null
  const sh = shape ?? p?.shape ?? "rect"
  const opts = {
    ink: ink ?? p?.ink,
    sub: sub ?? p?.sub,
    ring: ring ?? p?.ring,
    w: size ?? w ?? p?.w,
    h: size ?? h ?? p?.h,
    tilt: tilt ?? p?.tilt,
    ghost: ghost ?? p?.ghost,
    dashed: dashed ?? p?.dashed,
    stars: p?.stars,
    wear: p?.wear,
    seed: seed ?? name ?? t,
  }
  const res = memo(`stamp|${t}|${sh}|${JSON.stringify(opts)}`, () => stamp(t, sh, opts))
  return (
    <svg
      data-slot="stamp"
      data-ink="stamp"
      data-stamp={name ?? t}
      role="img"
      aria-label={label ?? t}
      focusable="false"
      viewBox={`0 0 ${res.w} ${res.h}`}
      width={res.w}
      height={res.h}
      style={style}
      className={cn("pointer-events-none shrink-0 overflow-visible", className)}
      dangerouslySetInnerHTML={{ __html: res.svg }}
      {...props}
    />
  )
}

export { Stamp }
