import {indexTrialsApi} from '../api/index-trials.js';
export const indexTrialsStore={items:[],async refresh(){this.items=await indexTrialsApi.list();return this.items;}};
