import type { StickerDef } from '@/lib/ink/art/types'
import { statusPointers } from '@/lib/ink/art/stickers/status-pointers'
import { spaceWeather } from '@/lib/ink/art/stickers/space-weather'
import { foodDrink } from '@/lib/ink/art/stickers/food-drink'
import { officeDesk } from '@/lib/ink/art/stickers/office-desk'
import { natureAnimals } from '@/lib/ink/art/stickers/nature-animals'
import { facesCelebrate } from '@/lib/ink/art/stickers/faces-celebrate'
import { badgesStamps } from '@/lib/ink/art/stickers/badges-stamps'

export const stickerBatches = { statusPointers, spaceWeather, foodDrink, officeDesk, natureAnimals, facesCelebrate, badgesStamps } as const
export const stickers = { ...statusPointers, ...spaceWeather, ...foodDrink, ...officeDesk, ...natureAnimals, ...facesCelebrate, ...badgesStamps } satisfies Record<string, StickerDef>
export type StickerName = keyof typeof stickers
