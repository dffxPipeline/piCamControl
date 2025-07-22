#!/usr/bin/env python3
import argparse
import numpy as np
import cv2
import os


def resync_video_with_pts(mjpeg_path, pts_path, output_path, master_pts, target_fps=24, debug=False):
    # Load PTS and normalize to start at 0
    pts = np.loadtxt(pts_path)
    pts -= pts[0]

    # Normalize master_pts to start at 0
    master_pts = master_pts - master_pts[0]

    # Open MJPEG video
    cap = cv2.VideoCapture(mjpeg_path)
    if debug:
        print(f"[DEBUG] Opened video: {mjpeg_path}")

    # Read all frames into memory using robust loop
    frames = []
    frame_index = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            if debug:
                print(f"[DEBUG] End of video stream at frame {frame_index}")
            break
        frames.append(frame)
        frame_index += 1
        if debug and frame_index % 50 == 0:
            print(f"[DEBUG] Read frame {frame_index}")
    cap.release()

    if not frames:
        raise RuntimeError("No frames read from input video.")

    # Find closest matching frame indices to master timeline
    indices = np.searchsorted(pts, master_pts)
    indices = np.clip(indices, 0, len(frames) - 1)

    # Write out new synced video or PNG/JPEG sequence
    if output_path.endswith(".pngseq"):
        img_dir = output_path[:-7]
        if not os.path.exists(img_dir):
            os.makedirs(img_dir)
        total_frames = len(indices)
        last_percent = -1
        for i, idx in enumerate(indices):
            img_path = os.path.join(img_dir, f"frame_{i+1:05d}.png")
            cv2.imwrite(img_path, frames[idx])
            percent = int((i + 1) / total_frames * 100)
            if percent != last_percent and percent % 5 == 0:
                print(f"    Progress: {percent}%", end='\r', flush=True)
                last_percent = percent
            if debug and i % 50 == 0:
                print(f"[DEBUG] Exporting PNG frame {i} using source frame {idx}")
        print("    Progress: 100%")
        print(f"[✓] PNG sequence saved to {img_dir}")
    elif output_path.endswith(".jpegseq"):
        img_dir = output_path[:-8]
        if not os.path.exists(img_dir):
            os.makedirs(img_dir)
        total_frames = len(indices)
        last_percent = -1
        for i, idx in enumerate(indices):
            img_path = os.path.join(img_dir, f"frame_{i+1:05d}.jpg")
            cv2.imwrite(img_path, frames[idx], [int(cv2.IMWRITE_JPEG_QUALITY), 100])
            percent = int((i + 1) / total_frames * 100)
            if percent != last_percent and percent % 5 == 0:
                print(f"    Progress: {percent}%", end='\r', flush=True)
                last_percent = percent
            if debug and i % 50 == 0:
                print(f"[DEBUG] Exporting JPEG frame {i} using source frame {idx}")
        print("    Progress: 100%")
        print(f"[✓] JPEG sequence saved to {img_dir}")
    else:
        height, width = frames[0].shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, target_fps, (width, height))
        total_frames = len(indices)
        last_percent = -1
        for i, idx in enumerate(indices):
            out.write(frames[idx])
            percent = int((i + 1) / total_frames * 100)
            if percent != last_percent and percent % 5 == 0:
                print(f"    Progress: {percent}%", end='\r', flush=True)
                last_percent = percent
            if debug and i % 50 == 0:
                print(f"[DEBUG] Writing frame {i} using source frame {idx}")
        print("    Progress: 100%")
        out.release()
        print(f"[✓] Synced video saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Batch resync MJPEG videos using PTS to match master timeline")
    parser.add_argument('--input_dir', required=True, help="Directory containing .mjpeg and .pts files")
    parser.add_argument('--master', required=True, help="Path to master camera PTS file")
    parser.add_argument('--output_dir', required=True, help="Directory to save synced .mp4 files")
    parser.add_argument('--fps', type=int, default=24, help="Target framerate for output videos")
    parser.add_argument('--debug', action='store_true', help="Enable debug output")
    parser.add_argument('--export_png', action='store_true', help="Export PNG sequence instead of MP4 video")
    parser.add_argument('--export_jpeg', action='store_true', help="Export high quality JPEG sequence instead of MP4/PNG")
    parser.add_argument('--start_frame', type=int, default=0, help="Start frame index in master timeline (default: 0)")
    parser.add_argument('--end_frame', type=int, default=None, help="End frame index in master timeline (default: last frame)")
    args = parser.parse_args()

    if not os.path.exists(args.input_dir):
        raise FileNotFoundError(f"Missing input directory: {args.input_dir}")
    if not os.path.exists(args.master):
        raise FileNotFoundError(f"Missing master PTS file: {args.master}")
    if not os.path.exists(args.output_dir):
        os.makedirs(args.output_dir)

    master_pts = np.loadtxt(args.master)
    # Apply frame range
    start = args.start_frame
    end = args.end_frame if args.end_frame is not None else len(master_pts)
    master_pts = master_pts[start:end]

    # Find all .mjpeg files in input_dir, process in alphabetical order
    mjpeg_files = sorted([f for f in os.listdir(args.input_dir) if f.lower().endswith('.mjpeg')])
    for idx, fname in enumerate(mjpeg_files):
        mjpeg_path = os.path.join(args.input_dir, fname)
        pts_path = os.path.join(args.input_dir, os.path.splitext(fname)[0] + '.pts')
        cam_dir = f"cam{idx+1:02d}"
        if args.export_jpeg:
            output_path = os.path.join(args.output_dir, cam_dir, ".jpegseq")
        elif args.export_png:
            output_path = os.path.join(args.output_dir, cam_dir, ".pngseq")
        else:
            output_path = os.path.join(args.output_dir, os.path.splitext(fname)[0] + '.mp4')

        if not os.path.exists(pts_path):
            print(f"[!] Skipping {fname}: missing corresponding .pts file.")
            continue

        print(f"[→] Syncing {fname} ...")
        try:
            resync_video_with_pts(
                mjpeg_path=mjpeg_path,
                pts_path=pts_path,
                output_path=output_path,
                master_pts=master_pts,
                target_fps=args.fps,
                debug=args.debug
            )
            print(f"[✓] Finished syncing {fname}")
        except Exception as e:
            print(f"[ERROR] Failed to process {fname}: {e}")


if __name__ == "__main__":
    main()
