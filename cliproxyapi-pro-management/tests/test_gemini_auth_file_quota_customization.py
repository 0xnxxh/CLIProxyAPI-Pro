import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / 'apply_customizations.py'
SPEC = importlib.util.spec_from_file_location('apply_customizations', MODULE_PATH)
assert SPEC and SPEC.loader
CUSTOMIZATIONS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CUSTOMIZATIONS)


CONSTANTS_SOURCE = """export type QuotaProviderType = 'antigravity' | 'claude' | 'codex' | 'kimi' | 'xai';
export const QUOTA_PROVIDER_TYPES = new Set<QuotaProviderType>([
  'antigravity',
  'claude',
  'codex',
  'kimi',
  'xai',
]);
"""

QUOTA_SECTION_SOURCE = """import {
  ANTIGRAVITY_CONFIG,
  CLAUDE_CONFIG,
  CODEX_CONFIG,
  KIMI_CONFIG,
  XAI_CONFIG,
} from '@/components/quota';

const getQuotaConfig = (type: QuotaProviderType) => {
  if (type === 'antigravity') return ANTIGRAVITY_CONFIG;
  if (type === 'claude') return CLAUDE_CONFIG;
  if (type === 'codex') return CODEX_CONFIG;
  if (type === 'kimi') return KIMI_CONFIG;
  if (type === 'xai') return XAI_CONFIG;
  return assertNever(type);
};

const quota = useQuotaStore((state) => {
    if (quotaType === 'antigravity') return state.antigravityQuota[file.name] as QuotaState;
    if (quotaType === 'claude') return state.claudeQuota[file.name] as QuotaState;
    if (quotaType === 'codex') return state.codexQuota[file.name] as QuotaState;
    if (quotaType === 'kimi') return state.kimiQuota[file.name] as QuotaState;
    if (quotaType === 'xai') return state.xaiQuota[file.name] as QuotaState;
    return assertNever(quotaType);
});

const updateQuotaState = useQuotaStore((state) => {
    if (quotaType === 'antigravity')
      return state.setAntigravityQuota as unknown as (updater: unknown) => void;
    if (quotaType === 'claude')
      return state.setClaudeQuota as unknown as (updater: unknown) => void;
    if (quotaType === 'codex') return state.setCodexQuota as unknown as (updater: unknown) => void;
    if (quotaType === 'kimi') return state.setKimiQuota as unknown as (updater: unknown) => void;
    if (quotaType === 'xai') return state.setXaiQuota as unknown as (updater: unknown) => void;
    return assertNever(quotaType);
});
"""

CARD_SOURCE = """const providerCardClass =
    quotaType === 'antigravity'
      ? styles.antigravityCard
      : quotaType === 'claude'
        ? styles.claudeCard
        : quotaType === 'codex'
          ? styles.codexCard
          : quotaType === 'kimi'
            ? styles.kimiCard
            : quotaType === 'xai'
              ? styles.xaiCard
              : '';
"""

STYLES_SOURCE = """.codexCard {
  background: transparent;
}

.kimiCard {
  background: transparent;
}
"""


class GeminiAuthFileQuotaCustomizationTest(unittest.TestCase):
    def setUp(self) -> None:
        CUSTOMIZATIONS._writes.clear()

    def test_wires_gemini_quota_into_auth_file_cards(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir)
            components = target / 'src/features/authFiles/components'
            components.mkdir(parents=True)
            (target / 'src/pages').mkdir(parents=True)
            (target / 'src/features/authFiles/constants.ts').write_text(CONSTANTS_SOURCE)
            (components / 'AuthFileQuotaSection.tsx').write_text(QUOTA_SECTION_SOURCE)
            (components / 'AuthFileCard.tsx').write_text(CARD_SOURCE)
            (target / 'src/pages/AuthFilesPage.module.scss').write_text(STYLES_SOURCE)

            CUSTOMIZATIONS.patch_auth_files_gemini_quota(target)
            CUSTOMIZATIONS.flush_writes()

            constants = (target / 'src/features/authFiles/constants.ts').read_text()
            section = (components / 'AuthFileQuotaSection.tsx').read_text()
            card = (components / 'AuthFileCard.tsx').read_text()
            styles = (target / 'src/pages/AuthFilesPage.module.scss').read_text()

            self.assertIn("'gemini-cli' | 'kimi'", constants)
            self.assertIn("  'gemini-cli',", constants)
            self.assertIn('GEMINI_CLI_CONFIG', section)
            self.assertIn('state.geminiCliQuota[file.name]', section)
            self.assertIn('state.setGeminiCliQuota', section)
            self.assertIn("quotaType === 'gemini-cli'", card)
            self.assertIn('.geminiCliCard {', styles)

            CUSTOMIZATIONS.patch_auth_files_gemini_quota(target)
            CUSTOMIZATIONS.flush_writes()
            self.assertEqual(constants, (target / 'src/features/authFiles/constants.ts').read_text())
            self.assertEqual(section, (components / 'AuthFileQuotaSection.tsx').read_text())
            self.assertEqual(card, (components / 'AuthFileCard.tsx').read_text())
            self.assertEqual(styles, (target / 'src/pages/AuthFilesPage.module.scss').read_text())


if __name__ == '__main__':
    unittest.main()
