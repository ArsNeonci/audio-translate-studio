import {readFile, stat} from 'node:fs/promises';
import path from 'node:path';
import {dataRoot} from './python';
type Sample = {id:string;key:string;text:string;duration_ms:number};
export const previewRoot = path.join(/*turbopackIgnore: true*/ process.cwd(), 'public', 'voice-previews');
export async function voiceSamples() {
  const manifest = JSON.parse(await readFile(/*turbopackIgnore: true*/ path.join(/*turbopackIgnore: true*/ previewRoot, 'manifest.json'), 'utf8').catch(()=>'{"voices":[]}')) as {voices:Sample[]};
  const valid = await Promise.all(manifest.voices.filter(item=>/^[a-f0-9]{64}$/.test(item.key)).map(async item=>{
    const file = path.join(/*turbopackIgnore: true*/ previewRoot, `${item.key}.wav`);
    return await stat(/*turbopackIgnore: true*/ file).then(info=>info.isFile()?item:null).catch(()=>null);
  }));
  return valid.filter((item):item is Sample=>item !== null);
}
export async function previewBuilderStatus() {
  const state = JSON.parse(await readFile(/*turbopackIgnore: true*/ path.join(/*turbopackIgnore: true*/ dataRoot, 'config', 'voice-preview-builder.json'), 'utf8').catch(()=>'{"status":"NOT_BUILT"}')) as {status:string};
  return state.status;
}
