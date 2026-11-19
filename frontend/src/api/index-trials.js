import {api} from './client.js';
export const indexTrialsApi={
  list:()=>api('/index-trials'),
  create:data=>api('/index-trials','POST',data),
  detail:id=>api('/index-trials/'+id),
  retry:id=>api('/index-trials/'+id+'/retry','POST')
};
