import {
  TrayArrowDown,
  FileText,
  Scan,
  Sparkle,
  Storefront,
  FolderSimple,
  CopySimple,
  Scales,
  ListChecks,
  Calculator,
  Gavel,
  CloudCheck,
  FlagBanner,
  Warning,
} from '@phosphor-icons/react';
import type { Icon } from '@phosphor-icons/react';

const STAGE_ICONS: Record<string, Icon> = {
  RECEIVED: TrayArrowDown,
  DOCUMENT_PROCESSING: FileText,
  OCR_PROCESSING: Scan,
  LLM_EXTRACTION: Sparkle,
  VENDOR_MATCHING: Storefront,
  PO_MATCHING: FolderSimple,
  DUPLICATE_CHECK: CopySimple,
  AMOUNT_VALIDATION: Scales,
  LINE_ITEM_VALIDATION: ListChecks,
  TAX_VALIDATION: Calculator,
  DECISION: Gavel,
  PERSISTENCE: CloudCheck,
  COMPLETED: FlagBanner,
  FAILED: Warning,
};

export function stageIcon(stage: string): Icon {
  return STAGE_ICONS[stage] ?? FileText;
}

export const STAGE_ORDER = [
  'RECEIVED', 'DOCUMENT_PROCESSING', 'OCR_PROCESSING', 'LLM_EXTRACTION',
  'VENDOR_MATCHING', 'PO_MATCHING', 'DUPLICATE_CHECK',
  'AMOUNT_VALIDATION', 'LINE_ITEM_VALIDATION', 'TAX_VALIDATION',
  'DECISION', 'PERSISTENCE', 'COMPLETED',
] as const;
