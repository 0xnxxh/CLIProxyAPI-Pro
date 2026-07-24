import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / 'apply_customizations.py'
SPEC = importlib.util.spec_from_file_location('apply_customizations', MODULE_PATH)
assert SPEC and SPEC.loader
CUSTOMIZATIONS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CUSTOMIZATIONS)


AUTH_FILES_PAGE_SOURCE = """import { useAuthStore, useNotificationStore, useThemeStore, useQuotaStore } from '@/stores';

const resolveStatusFilterMode = (
  problemOnly: boolean,
  disabledOnly: boolean
): AuthFilesStatusFilterMode => {
  if (problemOnly) return 'problem';
  if (disabledOnly) return 'disabled';
  return 'all';
};

export function AuthFilesPage() {
  const normalizedFilter = normalizeProviderKey(String(filter));
  const enabledOnly = statusFilterMode === 'enabled';

  const handleSortModeChange = useCallback(
    (value: string) => {
      if (!isAuthFilesSortMode(value) || value === sortMode) return;
      setSortMode(value);
      setPage(1);
    },
    [sortMode]
  );

  const handleStatusFilterModeChange = useCallback((nextMode: AuthFilesStatusFilterMode) => {
    setStatusFilterMode(nextMode);
    setPage(1);
  }, []);

  const sortOptions = useMemo(
    () => [
      { value: 'default', label: t('auth_files.sort_default') },
      { value: 'az', label: t('auth_files.sort_az') },
      { value: 'priority', label: t('auth_files.sort_priority') },
    ],
    [t]
  );

  const sorted = useMemo(() => {
    const copy = [...filtered];
    if (sortMode === 'default') {
      copy.sort((a, b) => {
        const providerA = normalizeProviderKey(String(a.provider ?? a.type ?? 'unknown'));
        const providerB = normalizeProviderKey(String(b.provider ?? b.type ?? 'unknown'));
        const providerCompare = providerA.localeCompare(providerB);
        if (providerCompare !== 0) return providerCompare;
        return a.name.localeCompare(b.name);
      });
    } else if (sortMode === 'az') {
      copy.sort((a, b) => a.name.localeCompare(b.name));
    } else if (sortMode === 'priority') {
      copy.sort((a, b) => {
        const pa = parsePriorityValue(a.priority) ?? 0;
        const pb = parsePriorityValue(b.priority) ?? 0;
        return pb - pa; // 高优先级排前面
      });
    }
    return copy;
  }, [filtered, sortMode]);

  return (
    <Select
                      value={sortMode}
                      options={sortOptions}
                      onChange={handleSortModeChange}
    />
  );
}
"""


UI_STATE_SOURCE = """export const AUTH_FILES_SORT_MODES = ['default', 'az', 'priority'] as const;
export type AuthFilesSortMode = (typeof AUTH_FILES_SORT_MODES)[number];
"""


class AuthFilesSortingCustomizationTest(unittest.TestCase):
    def setUp(self) -> None:
        CUSTOMIZATIONS._writes.clear()

    def test_adds_provider_scoped_sorting_and_state_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            pages_dir = target / 'src/pages'
            feature_dir = target / 'src/features/authFiles'
            pages_dir.mkdir(parents=True)
            feature_dir.mkdir(parents=True)
            page_path = pages_dir / 'AuthFilesPage.tsx'
            ui_state_path = feature_dir / 'uiState.ts'
            page_path.write_text(AUTH_FILES_PAGE_SOURCE)
            ui_state_path.write_text(UI_STATE_SOURCE)

            CUSTOMIZATIONS.patch_auth_files_page_sorting(target)
            CUSTOMIZATIONS.flush_writes()

            page = page_path.read_text()
            ui_state = ui_state_path.read_text()

            self.assertIn("['default', 'az', 'priority', 'plan', 'quota']", ui_state)
            self.assertIn("from '@/features/authFiles/planSort'", page)
            self.assertIn("from '@/features/authFiles/quotaSort'", page)
            self.assertIn(
                'const planSortAvailable = isAuthFilePlanSortProvider(normalizedFilter);',
                page,
            )
            self.assertIn(
                'const quotaSortAvailable = isAuthFileQuotaSortProvider(normalizedFilter);',
                page,
            )
            self.assertIn('if (selectedSortModeAvailable) return;', page)
            self.assertIn("options.push({ value: 'plan', label: t('auth_files.sort_plan_desc') });", page)
            self.assertIn("options.push({ value: 'quota', label: t('auth_files.sort_quota_desc') });", page)
            self.assertIn("selectedSortModeAvailable ? sortMode : 'default'", page)
            self.assertIn('compareAuthFilesByPlanDescending(a, b, quotaSearchStore)', page)
            self.assertIn('compareAuthFilesByAvailableQuotaDescending(a, b, quotaSearchStore)', page)
            self.assertIn('value={effectiveSortMode}', page)

            CUSTOMIZATIONS.patch_auth_files_page_sorting(target)
            CUSTOMIZATIONS.flush_writes()
            self.assertEqual(page, page_path.read_text())
            self.assertEqual(ui_state, ui_state_path.read_text())

    def test_adds_sort_locale_labels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            locales_dir = target / 'src/i18n/locales'
            locales_dir.mkdir(parents=True)
            for name in ('en.json', 'ru.json', 'zh-CN.json', 'zh-TW.json'):
                (locales_dir / name).write_text('{}')

            CUSTOMIZATIONS.patch_locales(target)
            CUSTOMIZATIONS.flush_writes()

            expected = {
                'en.json': ('Plan: High to Low', 'Available Quota: High to Low'),
                'ru.json': ('Тариф: по убыванию', 'Доступная квота: по убыванию'),
                'zh-CN.json': ('套餐从高到低', '可用额度从高到低'),
                'zh-TW.json': ('套餐由高到低', '可用額度由高到低'),
            }
            for name, labels in expected.items():
                data = json.loads((locales_dir / name).read_text())
                self.assertEqual(labels[0], data['auth_files']['sort_plan_desc'])
                self.assertEqual(labels[1], data['auth_files']['sort_quota_desc'])
                self.assertEqual('X Premium+', data['xai_quota']['plan_x_premium_plus'])
                self.assertIn('free_quota_window', data['xai_quota'])


if __name__ == '__main__':
    unittest.main()
