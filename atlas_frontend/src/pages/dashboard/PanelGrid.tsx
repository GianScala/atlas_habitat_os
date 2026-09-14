import { PanelCard } from '@/components/charts/PanelCard'

import type { DrawableGroup } from './drawable'

interface PanelGridProps {
  groups: DrawableGroup[]
  /** The span the charts are drawn from, for formatting their axes. */
  windowMinutes: number
  /** The next window out, offered by a panel that came back empty. */
  wider: { key: string; label: string } | null
  onWiden: (key: string) => void
}

/** The charts themselves, under their group headings. */
export function PanelGrid({ groups, windowMinutes, wider, onWiden }: PanelGridProps) {
  return (
    <>
      {groups.map((group) => (
        <section key={group.name} className="dashboard__group">
          <h2 className="dashboard__group-title">{group.name}</h2>
          <div className="dashboard__grid">
            {group.items.map((item) => (
              <PanelCard
                key={item.panel.id}
                panel={item.panel}
                colours={item.colours}
                dashes={item.dashes}
                windowMinutes={windowMinutes}
                filteredOut={item.filteredOut}
                wider={wider}
                onWiden={onWiden}
              />
            ))}
          </div>
        </section>
      ))}
    </>
  )
}
