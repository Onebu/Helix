import { useTranslation } from 'react-i18next'
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { PRESETS, PRESET_NAMES, type PresetResponse } from './evolution-presets'
import type { EvolutionRunRequest } from '../../client/types.gen'
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem, SelectGroup, SelectLabel, SelectSeparator } from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Save, Settings2, Trash2 } from 'lucide-react'
import { apiJson } from '@/lib/api-fetch'

interface PresetSelectorProps {
  activePreset: string | null
  isCustom: boolean
  onSelect: (presetName: string, values: Partial<EvolutionRunRequest>) => void
  currentValues: Partial<EvolutionRunRequest>
}

export default function PresetSelector({
  activePreset,
  isCustom,
  onSelect,
  currentValues,
}: PresetSelectorProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  // Save dialog state
  const [saveDialogOpen, setSaveDialogOpen] = useState(false)
  const [newPresetName, setNewPresetName] = useState('')

  // Manage dialog state
  const [manageDialogOpen, setManageDialogOpen] = useState(false)
  const [editingNames, setEditingNames] = useState<Record<number, string>>({})

  // Fetch custom presets
  const { data: customPresets = [] } = useQuery({
    queryKey: ['presets', 'evolution'],
    queryFn: () => apiJson<PresetResponse[]>('/api/presets/?type=evolution'),
  })

  // Create preset mutation
  const createMutation = useMutation({
    mutationFn: async (name: string) => {
      return apiJson<PresetResponse>('/api/presets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          type: 'evolution',
          data: currentValues,
          is_default: false,
        }),
      })
    },
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['presets', 'evolution'] })
      setSaveDialogOpen(false)
      setNewPresetName('')
      // Auto-select the newly created preset
      onSelect(`custom-${created.id}`, created.data as Partial<EvolutionRunRequest>)
    },
  })

  // Update preset mutation (rename)
  const updateMutation = useMutation({
    mutationFn: async ({ id, name }: { id: number; name: string }) => {
      return apiJson<PresetResponse>(`/api/presets/${encodeURIComponent(String(id))}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['presets', 'evolution'] })
    },
  })

  // Delete preset mutation
  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await apiJson<void>(`/api/presets/${encodeURIComponent(String(id))}`, { method: 'DELETE' })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['presets', 'evolution'] })
    },
  })

  function handleSelectChange(value: string) {
    // Look up values for the selected preset
    if ((PRESET_NAMES as readonly string[]).includes(value)) {
      const preset = PRESETS[value as (typeof PRESET_NAMES)[number]]
      onSelect(value, preset.values)
    } else if (value.startsWith('custom-')) {
      const id = parseInt(value.replace('custom-', ''), 10)
      const custom = customPresets.find((p) => p.id === id)
      if (custom) {
        onSelect(value, custom.data as Partial<EvolutionRunRequest>)
      }
    }
  }

  function handleSavePreset() {
    const name = newPresetName.trim()
    if (!name) return
    createMutation.mutate(name)
  }

  function handleRename(id: number) {
    const newName = (editingNames[id] ?? '').trim()
    if (!newName) return
    updateMutation.mutate({ id, name: newName })
    setEditingNames((prev) => {
      const next = { ...prev }
      delete next[id]
      return next
    })
  }

  function handleDelete(id: number, name: string) {
    if (!window.confirm(t('evolution.deletePresetConfirm', { name }))) return
    deleteMutation.mutate(id)
    // If the deleted preset was active, clear selection
    if (activePreset === `custom-${id}`) {
      onSelect('', {})
    }
  }

  const hasCustomPresets = customPresets.length > 0

  // Compute display label for the active preset
  function getDisplayLabel(): string | undefined {
    if (!activePreset) return undefined
    if ((PRESET_NAMES as readonly string[]).includes(activePreset)) {
      const preset = PRESETS[activePreset as (typeof PRESET_NAMES)[number]]
      return isCustom ? `${preset.label} ${t('evolution.modified')}` : preset.label
    }
    if (activePreset.startsWith('custom-')) {
      const id = parseInt(activePreset.replace('custom-', ''), 10)
      const custom = customPresets.find((p) => p.id === id)
      if (custom) return isCustom ? `${custom.name} ${t('evolution.modified')}` : custom.name
    }
    return undefined
  }

  return (
    <div className="flex items-center gap-2">
      {/* Preset dropdown */}
      <div className="flex-1">
        <Select value={activePreset ?? ''} onValueChange={handleSelectChange}>
          <SelectTrigger>
            <SelectValue placeholder={t('evolution.selectAPreset')}>
              {getDisplayLabel()}
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {hasCustomPresets ? (
              <>
                <SelectGroup>
                  <SelectLabel>{t('evolution.builtIn')}</SelectLabel>
                  {PRESET_NAMES.map((name) => (
                    <SelectItem key={name} value={name}>
                      {PRESETS[name].label} — {PRESETS[name].description}
                    </SelectItem>
                  ))}
                </SelectGroup>
                <SelectSeparator />
                <SelectGroup>
                  <SelectLabel>{t('evolution.customPresets')}</SelectLabel>
                  {customPresets.map((p) => (
                    <SelectItem key={`custom-${p.id}`} value={`custom-${p.id}`}>
                      {p.name}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </>
            ) : (
              <>
                {PRESET_NAMES.map((name) => (
                  <SelectItem key={name} value={name}>
                    {PRESETS[name].label} — {PRESETS[name].description}
                  </SelectItem>
                ))}
              </>
            )}
          </SelectContent>
        </Select>
      </div>

      {/* Save as Preset button */}
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => setSaveDialogOpen(true)}
        className="shrink-0"
      >
        <Save className="h-4 w-4 mr-1.5" />
        {t('evolution.saveAsPreset')}
      </Button>

      {/* Manage presets button */}
      {hasCustomPresets && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={() => {
            // Pre-populate editing names with current names
            const names: Record<number, string> = {}
            customPresets.forEach((p) => { names[p.id] = p.name })
            setEditingNames(names)
            setManageDialogOpen(true)
          }}
          className="shrink-0"
          title={t('evolution.managePresets')}
        >
          <Settings2 className="h-4 w-4" />
        </Button>
      )}

      {/* Save as preset dialog */}
      <Dialog open={saveDialogOpen} onOpenChange={setSaveDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('evolution.saveAsPreset')}</DialogTitle>
            <DialogDescription>
              {t('evolution.saveAsPresetDescription')}
            </DialogDescription>
          </DialogHeader>
          <div className="py-4">
            <label htmlFor="preset-name" className="text-sm font-medium text-foreground mb-1 block">
              {t('evolution.presetName')}
            </label>
            <Input
              id="preset-name"
              value={newPresetName}
              onChange={(e) => setNewPresetName(e.target.value)}
              placeholder={t('evolution.myCustomPreset')}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  handleSavePreset()
                }
              }}
              autoFocus
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => { setSaveDialogOpen(false); setNewPresetName('') }}
            >
              {t('common.cancel')}
            </Button>
            <Button
              type="button"
              onClick={handleSavePreset}
              disabled={!newPresetName.trim() || createMutation.isPending}
            >
              {createMutation.isPending ? t('evolution.saving') : t('common.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Manage presets dialog */}
      <Dialog open={manageDialogOpen} onOpenChange={setManageDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('evolution.managePresetsTitle')}</DialogTitle>
            <DialogDescription>
              {t('evolution.managePresetsDescription')}
            </DialogDescription>
          </DialogHeader>
          <div className="py-4 space-y-3 max-h-80 overflow-y-auto">
            {customPresets.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-6">
                {t('evolution.noCustomPresets')}
              </p>
            ) : (
              customPresets.map((p) => (
                <div key={p.id} className="flex items-center gap-2">
                  <Input
                    value={editingNames[p.id] ?? p.name}
                    onChange={(e) =>
                      setEditingNames((prev) => ({ ...prev, [p.id]: e.target.value }))
                    }
                    onBlur={() => {
                      const newName = (editingNames[p.id] ?? '').trim()
                      if (newName && newName !== p.name) {
                        handleRename(p.id)
                      }
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        handleRename(p.id)
                      }
                    }}
                    className="flex-1"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => handleDelete(p.id, p.name)}
                    className="shrink-0 text-destructive hover:text-destructive hover:bg-destructive/10"
                    title={`Delete "${p.name}"`}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setManageDialogOpen(false)}>
              {t('common.close')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
