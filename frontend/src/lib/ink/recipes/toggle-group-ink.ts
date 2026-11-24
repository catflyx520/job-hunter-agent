import { roundRectPoly } from '@/lib/ink/geom'
import { wash } from '@/lib/ink/fills'
import { clamp } from '@/lib/ink/rng'
import { box, dashedBox } from '@/lib/ink/shapes'
import { defineRecipe } from '@/lib/ink/recipes'

export interface ToggleGroupParams {
  joined: boolean
  disabled?: boolean
  invalid?: boolean
}

export const toggleGroupRecipe = defineRecipe<ToggleGroupParams>({
  id: 'toggle-group',
  kind: 'toggle-group',
  layers: ['rest', 'disabled'],
  pad: 12,
  draw(ink, { w, h }, { joined, disabled, invalid }, ctx) {
    const calm = ctx.calm
    if (!joined) return
    const r = clamp(Math.min(w, h) * 0.09, 2.2, 4.4)
    if (disabled) {
      ink.layer('disabled', () => {
        wash(ink, roundRectPoly(1.6, 1.6, w - 3.2, h - 3.2, r), 'pencil-mark', { alpha: 0.12, material: 'wash' })
        dashedBox(ink, 0, 0, w, h, { r, pen: 'pencil', opts: { color: 'pencil', width: 1.2 } })
      })
      return
    }
    const opts = { ...(w > 360 ? { simple: true } : {}), ...(invalid ? { width: 1.2 } : {}) }
    ink.layer('rest', () =>
      calm
        ? box(ink, 0, 0, w, h, { pen: invalid ? 'red.fine' : 'pencil.fine', corner: r, opts })
        : box(ink, 0, 0, w, h, { pen: invalid ? 'red' : 'ink', corner: r, opts })
    )
  },
})
