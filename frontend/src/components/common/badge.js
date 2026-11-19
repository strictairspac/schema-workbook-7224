import {RUN_STATES,COMBO_STATES} from '../../constants/enums.js';
import {esc} from '../../utils/html.js';
export const badge=value=>`<span class="badge ${esc(value)}">${esc(RUN_STATES[value]||value)}</span>`;
export const comboBadge=value=>`<span class="badge combo ${esc(value)}">${esc(COMBO_STATES[value]||value)}</span>`;
