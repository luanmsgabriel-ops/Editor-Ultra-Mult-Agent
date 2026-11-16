#!/usr/bin/env python3
"""Read-only encoded PCM clock audit; no assertion of perceptual listening."""
from pathlib import Path
import subprocess,json,hashlib,datetime
import numpy as np
from scipy.signal import correlate
ROOT=Path(__file__).resolve().parents[1]
VIDEO=ROOT/'output/Moto-330494-V2-Ritmo-e-Cenas.mp4'
REFERENCE=ROOT/'audio/reference-mix.wav'
RATE=48000

def decode(path):
 data=subprocess.check_output(['ffmpeg','-nostdin','-v','error','-i',str(path),'-vn','-ac','2','-ar',str(RATE),'-f','f32le','-'])
 return np.frombuffer(data,dtype='<f4').reshape(-1,2)

def match(y,r,start,end,search=.25):
 s=int(round(start*RATE));e=int(round(end*RATE));margin=int(search*RATE)
 lo=max(0,s-margin);hi=min(len(y),e+margin)
 a=r[s:e].astype(np.float64).mean(axis=1);b=y[lo:hi].astype(np.float64).mean(axis=1)
 if len(b)<len(a):raise ValueError('Audio too short for correlation window')
 a-=a.mean();n=len(a)
 numerator=correlate(b,a,mode='valid',method='fft')
 cs=np.r_[0,np.cumsum(b)];sq=np.r_[0,np.cumsum(b*b)]
 denom=np.sqrt(np.maximum((sq[n:]-sq[:-n])-(cs[n:]-cs[:-n])**2/n,1e-30)*np.sum(a*a))
 c=numerator/denom;i=int(np.argmax(c));lag=int(lo+i-s)
 return {'reference_window_seconds':[start,end],'window_center_seconds':(start+end)/2,'delay_samples':lag,'delay_ms':1000*lag/RATE,'delay_video_frames':24*lag/RATE,'correlation':float(c[i]),'sign_convention':'positive means encoded audio occurs later than reference','search_limit_seconds':search,'search_boundary_hit':i in(0,len(c)-1)}

def main():
 if not VIDEO.exists():raise SystemExit('Final MP4 not present; run after parent confirms completed mux.')
 probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(VIDEO)]))
 vs=next(s for s in probe['streams']if s['codec_type']=='video');a=next(s for s in probe['streams']if s['codec_type']=='audio')
 r=decode(REFERENCE)[:10*RATE];y=decode(VIDEO)
 glob=match(y,r,.5,9.5,.4)
 windows=[match(y,r,s,e,.25)for s,e in[(.25,1.75),(2.0,3.1),(3.19,4.4),(5.2,6.1),(7.1,8.1),(8.9,9.9)]]
 centers=np.array([v['window_center_seconds']for v in windows]);lags=np.array([v['delay_samples']for v in windows]);slope,intercept=np.polyfit(centers,lags,1)
 accents=[]
 for t,frame in[(3.67,88),(5.59,134),(7.51,180),(9.425,226)]:
  z=match(y,r,t-.18,t+.28,.15);actual=t+z['delay_samples']/RATE
  accents.append({'reference_cue_seconds':t,'authored_visual_frame':frame,'authored_visual_seconds':frame/24,'inferred_encoded_cue_seconds':actual,'audio_minus_authored_visual_ms':1000*(actual-frame/24),'audio_minus_authored_visual_frames':24*(actual-frame/24),'local_match':z,'note':'Cue time inherited from measured spectral center. Visual frame is authored intent, not independently confirmed rendered geometry apex.'})
 lag=glob['delay_samples'];ri=max(0,-lag);yi=max(0,lag);n=min(len(r)-ri,len(y)-yi)
 rr=r[ri:ri+n].astype(np.float64);yy=y[yi:yi+n].astype(np.float64)
 scale=float(np.sum(rr*yy)/np.sum(rr*rr));err=yy-scale*rr
 result={'status':'MATHEMATICAL_PCM_SYNC_AUDIT_COMPLETE','reviewed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'encoded_file':str(VIDEO.relative_to(ROOT)),'encoded_sha256':hashlib.sha256(VIDEO.read_bytes()).hexdigest(),'reference_file':str(REFERENCE.relative_to(ROOT)),'reference_sha256':hashlib.sha256(REFERENCE.read_bytes()).hexdigest(),'reference_range_seconds':[0,10],'method':'FFmpeg decode48000Hz stereo; normalized FFT cross-correlation of averaged channels, full central window and6local windows. Signed sample delay and linear drift fit. AAC spectral/quantization differences expected.','perceptual_listening_confirmed':False,'video':{k:vs.get(k)for k in['codec_name','width','height','r_frame_rate','duration','nb_frames','start_time']},'audio':{k:a.get(k)for k in['codec_name','sample_rate','channels','duration','start_time']},'container_duration_seconds':float(probe['format']['duration']),'decoded_audio_samples':len(y),'decoded_audio_duration_seconds':len(y)/RATE,'duration_note':'AAC decoder output may include final padding beyond stream duration. Playback uses mux timestamps/edit duration; no time drift should be inferred from tail padding alone.','global_match':glob,'window_matches':windows,'clock_drift':{'linear_delay_samples_per_second':float(slope),'intercept_samples':float(intercept),'drift_ppm':float(slope/RATE*1e6),'maximum_window_delay_spread_samples':int(np.ptp(lags)),'maximum_window_delay_spread_ms':float(np.ptp(lags)*1000/RATE),'note':'Regression over6windows; sample-grid precision is not perceptual certainty.'},'accents':accents,'signal':{'aligned_gain_ratio':scale,'gain_db':float(20*np.log10(abs(scale))),'aligned_error_rms_dbfs':float(20*np.log10(np.sqrt(np.mean(err**2))+1e-20)),'clipped_samples':int((abs(y)>=1).sum()),'sample_peak_dbfs':float(20*np.log10(abs(y).max()+1e-20))},'assessment':{'clock_pass':all(abs(v['delay_samples'])<=48 and v['correlation']>.98 and not v['search_boundary_hit']for v in windows),'criterion':'All local windows within1ms and correlation>.98; engineering criterion only.','audio_was_time_stretched':False if abs(slope/RATE)<1e-4 and min(v['correlation']for v in windows)>.98 else 'Not ruled out by this test','limitations':['No perceptual listening or rendered visual-apex verification in this report.','Authored cues retain their original centered-FFT uncertainty plus video frame quantization.','High correlation proves timing preservation relative to the given mix, not artistic synchronization approval.']}}
 out=ROOT/'analysis/encoded-audio-sync-v2.json';out.write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({'report':str(out.relative_to(ROOT)),'global':glob,'drift':result['clock_drift'],'assessment':result['assessment']}))
if __name__=='__main__':main()
