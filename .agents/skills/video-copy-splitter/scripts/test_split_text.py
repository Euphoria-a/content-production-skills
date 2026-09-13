#!/usr/bin/env python3

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import shutil
from pathlib import Path
from unittest.mock import patch

import split_text as splitter
from split_text import (
    FINAL_DELIVERY_NAMES,
    INTERNAL_TRANSACTION_NAMES,
    OUTPUT_NAMES,
    TRANSACTION_MANIFEST_NAME,
    acquire_output_lock,
    apply_pronunciation_map,
    build_outputs,
    final_delivery_names,
    process,
    read_text_detect_encoding,
    repair_mojibake,
    render_subtitles_plain,
    render_voice_plain,
    split_smart_units,
    split_voice,
    subtitle_character_count,
    subtitle_content_character_count,
    validate_final_delivery_dir,
    validate_internal_transaction,
    wrap_subtitles,
    wrap_smart_subtitles,
    write_outputs_safely,
)


class SplitTextTests(unittest.TestCase):
    def test_repair_common_gb18030_mojibake(self):
        repaired, count = repair_mojibake("瑙嗛")
        self.assertEqual(repaired, "视频")
        self.assertGreater(count, 0)

    def test_repair_only_mojibake_part_inside_clean_text(self):
        repaired, count = repair_mojibake("这里需要瑙嗛测试。")
        self.assertEqual(repaired, "这里需要视频测试。")
        self.assertGreater(count, 0)

    def test_clean_text_is_not_changed_by_mojibake_repair(self):
        text = "这里是正常的中文、数字2026和标点。"
        self.assertEqual(repair_mojibake(text), (text, 0))

    def test_lossy_mojibake_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "无法可靠自动修复"):
            repair_mojibake("这里出现锟斤拷内容")

    def test_gb18030_text_file_is_decoded_without_garbled_output(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "gb18030.txt"
            path.write_bytes("中文内容。".encode("gb18030"))
            self.assertEqual(read_text_detect_encoding(path), "中文内容。")

    def test_process_repairs_mojibake_before_building_master(self):
        data = process("瑙嗛内容。")
        self.assertEqual(data["normalized_source"], "视频内容。")
        self.assertGreater(data["mojibake_repair_count"], 0)

    def test_user_quote_example_is_not_over_split(self):
        lines = wrap_subtitles("他解释道：“这里不是终点，而是下一段旅程的起点。”")
        self.assertEqual(lines, ["他解释道：", "“这里不是终点，", "而是下一段旅程的起点。”"])
        self.assertEqual(len(lines[-1]), 12)

    def test_short_quote_is_atomic(self):
        units = split_smart_units("他说：“马上出发。”")
        self.assertEqual(units, ["他说：", "“马上出发。”"])

    def test_requested_punctuation_creates_units(self):
        self.assertEqual(split_smart_units("甲，乙；丙：丁。"), ["甲，", "乙；", "丙：", "丁。"])

    def test_smart_transcript_splits_long_unit_with_13_character_limit(self):
        line = "第二次世界大战的最后一场战斗发生在这里。"
        data = process(line)
        result = [row["text"] for row in data["subtitle_lines"]]
        self.assertGreater(len(result), 1)
        self.assertEqual("".join(result), line)
        self.assertTrue(all(subtitle_character_count(item) <= 13 for item in result))

    def test_trailing_comma_and_period_do_not_count_toward_limit(self):
        for punctuation in "，。,.":
            line = f"一二三四五六七八九十甲乙丙{punctuation}"
            self.assertEqual(len(line), 14)
            self.assertEqual(subtitle_character_count(line), 13)
            self.assertEqual(wrap_subtitles(line), [line])

    def test_punctuation_does_not_count_toward_chinese_or_digit_limit(self):
        self.assertEqual(subtitle_character_count("甲，乙"), 2)
        self.assertEqual(subtitle_character_count("一二三四五六七八九十甲乙丙；"), 13)
        self.assertEqual(wrap_subtitles("一二三四五六七八九十甲乙丙；"), ["一二三四五六七八九十甲乙丙；"])
        self.assertEqual(subtitle_character_count("2026年，7月。"), 7)

    def test_voice_has_no_subtitle_limit(self):
        text = "这是一句长度明显超过十三个字符但仍然应该保持完整的音色克隆训练文案。"
        self.assertEqual(split_voice(text), [text])

    def test_voice_never_splits_inside_a_sentence(self):
        text = "这句话很长，包含逗号；也包含分号：还包含冒号，但只能在完整句末切分。下一句保持独立。"
        self.assertEqual(split_voice(text), ["这句话很长，包含逗号；也包含分号：还包含冒号，但只能在完整句末切分。", "下一句保持独立。"])

    def test_pronunciation_map_only_changes_voice_units(self):
        data = process("长白山景色壮美，泾渭分明。", {"长白山": "常白山", "泾渭": "经位"})
        self.assertEqual(data["voice_units"][0]["voice_text"], "常白山景色壮美，经位分明。")
        self.assertEqual("".join(row["text"] for row in data["subtitle_lines"]), "长白山景色壮美，泾渭分明。")
        self.assertEqual(data["source_sentences"][0]["source_sentence_text"], "长白山景色壮美，泾渭分明。")

    def test_voice_output_contains_only_plain_sentences(self):
        data = process("第一句。第二句。")
        self.assertEqual(render_voice_plain(data["voice_units"]), "第一句。\n第二句。\n")

    def test_smart_transcript_output_contains_only_plain_copy(self):
        data = process("这里说明第一层含义，接着说明第二层含义。")
        rendered = render_subtitles_plain(data["subtitle_lines"])
        self.assertEqual(rendered, "\n".join(row["text"] for row in data["subtitle_lines"]) + "\n")
        self.assertNotIn("M001", rendered)
        self.assertNotIn("P001", rendered)
        self.assertNotIn("智能文稿", rendered)

    def test_reviewed_smart_transcript_matches_excellent_sample_style(self):
        text = "第二次世界大战的最后一场战斗发生在这里。因此，这座东北边境的地下要塞，被视为第二次世界大战的终结之地。"
        reviewed = [
            "第二次世界大战的",
            "最后一场战斗发生在这里。",
            "因此，",
            "这座东北边境的地下要塞，",
            "被视为第二次世界大战的",
            "终结之地。",
        ]
        data = process(text, smart_transcript_lines=reviewed)
        self.assertEqual([row["text"] for row in data["subtitle_lines"]], reviewed)
        self.assertEqual(render_subtitles_plain(data["subtitle_lines"]), "\n".join(reviewed) + "\n")

    def test_reviewed_smart_transcript_rejects_line_over_13(self):
        text = "一二三四五六七八九十甲乙丙丁。"
        with self.assertRaisesRegex(ValueError, "超过13个中文字符或数字"):
            process(text, smart_transcript_lines=[text])

    def test_reviewed_smart_transcript_must_reconstruct_source_exactly(self):
        with self.assertRaises(ValueError):
            process("原文必须保持完整。", smart_transcript_lines=["原文被修改。"])

    def test_invalid_pronunciation_map_is_rejected(self):
        with self.assertRaises(ValueError):
            apply_pronunciation_map("测试。", {"": "测"})

    def test_pronunciation_replacement_does_not_cascade(self):
        with self.assertRaises(ValueError):
            apply_pronunciation_map("长白山。", {"长白山": "常白山", "常": "尝"})

    def test_structured_pronunciation_review_is_scoped_to_sentence(self):
        text = "长白山很美。这里很长。"
        review = {
            "review_complete": True,
            "source_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "entries": [
                {
                    "source": "长白山",
                    "target_pronunciation": "cháng bái shān",
                    "replacement": "常白山",
                    "sentence_ids": ["S001"],
                    "review_status": "已替换",
                    "reason": "专名多音字",
                },
                {
                    "source": "长",
                    "target_pronunciation": "cháng",
                    "replacement": "常",
                    "sentence_ids": ["S002"],
                    "review_status": "已替换",
                    "reason": "多音字",
                },
            ],
        }
        data = process(text, review)
        self.assertEqual([row["voice_text"] for row in data["voice_units"]], ["常白山很美。", "这里很常。"])

    def test_unfinished_pronunciation_review_is_rejected(self):
        text = "长白山很美。"
        review = {"review_complete": False, "source_sha256": hashlib.sha256(text.encode()).hexdigest(), "entries": []}
        with self.assertRaises(ValueError):
            process(text, review)

    def test_source_voice_and_caption_have_independent_ids(self):
        data = process("第一句。第二句，继续说。")
        self.assertEqual([row["id"] for row in data["source_sentences"]], ["S001", "S002"])
        self.assertEqual([row["sentence_id"] for row in data["voice_units"]], ["S001", "S002"])
        self.assertTrue(all(row["id"].startswith("M") and row["sentence_id"].startswith("S") for row in data["subtitle_lines"]))

    def test_closing_punctuation_never_becomes_its_own_line(self):
        data = process("一二三四五六七八九十甲乙丙。")
        lines = [row["text"] for row in data["subtitle_lines"]]
        self.assertTrue(all(line[0] not in "，。；：！？、”’」』）》】" for line in lines))
        self.assertNotIn("。", lines)

    def test_caption_records_effective_and_raw_lengths(self):
        data = process("一二三四五六七八九十甲乙丙。")
        self.assertEqual(data["subtitle_lines"], [{
            "id": "M001",
            "sentence_id": "S001",
            "paragraph_id": "P001",
            "text": "一二三四五六七八九十甲乙丙。",
            "length": 13,
            "raw_length": 14,
            "content_length": 13,
        }])

    def test_semantic_wrapping_never_leaves_one_or_two_content_characters(self):
        lines = wrap_smart_subtitles("这是第一层含义，接着补充更完整的第二层含义并收尾。")
        self.assertTrue(all(subtitle_content_character_count(line) >= 3 for line in lines))
        self.assertEqual("".join(lines), "这是第一层含义，接着补充更完整的第二层含义并收尾。")

    def test_short_punctuation_unit_merges_with_neighboring_meaning(self):
        lines = wrap_smart_subtitles("对，接下来说明这段内容为什么需要完整表达。")
        self.assertNotEqual(lines[0], "对，")
        self.assertTrue(lines[0].startswith("对，接下来"))
        self.assertTrue(all(subtitle_content_character_count(line) >= 3 for line in lines))

    def test_long_line_rebalances_two_character_tail(self):
        lines = wrap_subtitles("一二三四五六七八九十甲乙丙丁戊。")
        self.assertTrue(all(subtitle_content_character_count(line) >= 3 for line in lines))
        self.assertEqual("".join(lines), "一二三四五六七八九十甲乙丙丁戊。")

    def test_protected_term_and_number_unit_are_not_split(self):
        data = process(
            "这里藏着规模庞大的地下工事遗址。面积达到四千四百平方公里。",
            protected_terms=["地下工事", "规模庞大"],
        )
        lines = [row["text"] for row in data["subtitle_lines"]]
        self.assertTrue(any("地下工事" in line for line in lines))
        self.assertTrue(any("四千四百平方公里" in line for line in lines))

    def test_minimum_duration_uses_configured_speech_rate(self):
        data = process("这是一句用于计算最低旁白时长的测试句子。", chars_per_second=4.0)
        sentence = data["source_sentences"][0]
        self.assertGreater(sentence["minimum_duration_seconds"], 0)

    def sample_outputs(self):
        return build_outputs(process("第一句。第二句。"))

    def test_safe_writer_generates_all_files_in_new_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            output_dir = Path(temp) / "new-output"
            write_outputs_safely(output_dir, self.sample_outputs())
            self.assertEqual(sorted(path.name for path in output_dir.iterdir()), sorted(INTERNAL_TRANSACTION_NAMES))
            validate_internal_transaction(output_dir)
            self.assertFalse(any(".stage-" in path.name for path in output_dir.parent.iterdir()))

    def test_existing_target_blocks_all_writes_by_default(self):
        with tempfile.TemporaryDirectory() as temp:
            output_dir = Path(temp) / "output"
            output_dir.mkdir()
            protected = output_dir / "01-voice-cloning-copy.txt"
            protected.write_text("必须保留", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                write_outputs_safely(output_dir, self.sample_outputs())
            self.assertEqual(protected.read_text(encoding="utf-8"), "必须保留")
            self.assertEqual([path.name for path in output_dir.iterdir()], [protected.name])

    def test_all_conflicts_are_listed_together(self):
        with tempfile.TemporaryDirectory() as temp:
            output_dir = Path(temp) / "output"
            output_dir.mkdir()
            conflicts = [output_dir / OUTPUT_NAMES[0], output_dir / OUTPUT_NAMES[2]]
            for path in conflicts:
                path.write_text("旧内容", encoding="utf-8")
            with self.assertRaises(FileExistsError) as caught:
                write_outputs_safely(output_dir, self.sample_outputs())
            message = str(caught.exception)
            self.assertTrue(all(str(path) in message for path in conflicts))

    def test_staging_failure_leaves_existing_file_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            output_dir = Path(temp) / "output"
            output_dir.mkdir()
            protected = output_dir / "01-voice-cloning-copy.txt"
            protected.write_text("旧成果", encoding="utf-8")
            with patch.object(Path, "write_text", side_effect=OSError("模拟暂存失败")):
                with self.assertRaises(OSError):
                    write_outputs_safely(output_dir, self.sample_outputs(), force=True)
            self.assertEqual(protected.read_text(encoding="utf-8"), "旧成果")
            self.assertFalse(any(".stage-" in path.name for path in output_dir.parent.iterdir()))

    def test_force_creates_recoverable_backup_before_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            output_dir = Path(temp) / "output"
            output_dir.mkdir()
            protected = output_dir / "01-voice-cloning-copy.txt"
            protected.write_text("旧成果", encoding="utf-8")
            backup_dir = write_outputs_safely(
                output_dir,
                self.sample_outputs(),
                force=True,
                timestamp="20260728-153000",
            )
            self.assertIsNotNone(backup_dir)
            self.assertEqual((backup_dir / protected.name).read_text(encoding="utf-8"), "旧成果")
            self.assertNotEqual(protected.read_text(encoding="utf-8"), "旧成果")

    def test_commit_failure_rolls_back_old_files(self):
        with tempfile.TemporaryDirectory() as temp:
            output_dir = Path(temp) / "output"
            output_dir.mkdir()
            protected = output_dir / "01-voice-cloning-copy.txt"
            protected.write_text("旧成果", encoding="utf-8")
            calls = 0

            def fail_during_commit(source, destination):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("模拟提交失败")
                os.replace(source, destination)

            with self.assertRaises(OSError):
                write_outputs_safely(
                    output_dir,
                    self.sample_outputs(),
                    force=True,
                    replace_fn=fail_during_commit,
                    timestamp="20260728-153001",
                )
            self.assertEqual(protected.read_text(encoding="utf-8"), "旧成果")
            self.assertFalse((output_dir / "00-normalized-source.md").exists())

    def test_manifest_binds_every_internal_file_to_one_transaction(self):
        with tempfile.TemporaryDirectory() as temp:
            output_dir = Path(temp) / "output"
            outputs = self.sample_outputs()
            write_outputs_safely(output_dir, outputs)
            manifest = validate_internal_transaction(output_dir)
            self.assertEqual(manifest["input_sha256"], json.loads(outputs["project-data.json"])["source_sha256"])
            self.assertEqual({item["name"] for item in manifest["files"]}, set(OUTPUT_NAMES))
            self.assertEqual(len({manifest["transaction_id"]}), 1)
            (output_dir / OUTPUT_NAMES[0]).write_text("被篡改", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_internal_transaction(output_dir)

    def test_lock_creation_permission_failure_leaves_no_target(self):
        with tempfile.TemporaryDirectory() as temp:
            output_dir = Path(temp) / "output"
            with patch("split_text._open_kernel_lock", side_effect=PermissionError("模拟无权限创建锁")):
                with self.assertRaises(PermissionError):
                    write_outputs_safely(output_dir, self.sample_outputs())
            self.assertFalse(output_dir.exists())

    def test_cross_filesystem_publish_failure_keeps_old_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            output_dir = Path(temp) / "output"
            output_dir.mkdir()
            protected = output_dir / "旧成果.txt"
            protected.write_text("必须保留", encoding="utf-8")
            calls = 0

            def fail_cross_filesystem(source, destination):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError(18, "模拟跨文件系统重命名失败")
                os.replace(source, destination)

            with self.assertRaises(OSError):
                write_outputs_safely(output_dir, self.sample_outputs(), force=True, replace_fn=fail_cross_filesystem)
            self.assertEqual(protected.read_text(encoding="utf-8"), "必须保留")
            self.assertFalse((output_dir / OUTPUT_NAMES[0]).exists())

    def test_force_cannot_bypass_active_directory_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            output_dir = Path(temp) / "output"
            with acquire_output_lock(output_dir, "a" * 64):
                with self.assertRaises(FileExistsError):
                    write_outputs_safely(output_dir, self.sample_outputs(), force=True)
            self.assertFalse(output_dir.exists())

    def test_persistent_unlocked_lock_file_needs_no_stale_takeover(self):
        with tempfile.TemporaryDirectory() as temp:
            output_dir = Path(temp) / "output"
            lock_path = output_dir.parent / f".{output_dir.name}.video-copy-splitter.lock"
            lock_path.write_text('{"transaction_id":"旧诊断信息"}', encoding="utf-8")
            write_outputs_safely(output_dir, self.sample_outputs())
            validate_internal_transaction(output_dir)
            self.assertTrue(lock_path.exists())

    def test_deterministic_three_party_aba_thread_sequence_keeps_active_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            output_dir = Path(temp) / "output"
            lock_path = output_dir.parent / f".{output_dir.name}.video-copy-splitter.lock"
            lock_path.write_text('{"transaction_id":"陈旧诊断信息"}', encoding="utf-8")
            start = threading.Barrier(3)
            release = threading.Event()
            acquired = threading.Event()
            blocked = threading.Event()
            outcomes = []
            guard = threading.Lock()

            def contender(transaction_id):
                start.wait()
                try:
                    with acquire_output_lock(
                        output_dir,
                        "c" * 64,
                        transaction_id=transaction_id,
                    ):
                        with guard:
                            outcomes.append((transaction_id, "acquired"))
                        acquired.set()
                        release.wait(timeout=10)
                except FileExistsError:
                    with guard:
                        outcomes.append((transaction_id, "blocked"))
                    blocked.set()

            threads = [
                threading.Thread(target=contender, args=("接管者A",)),
                threading.Thread(target=contender, args=("接管者B",)),
            ]
            for thread in threads:
                thread.start()
            start.wait()
            self.assertTrue(acquired.wait(timeout=10))
            self.assertTrue(blocked.wait(timeout=10))
            active = json.loads(lock_path.read_text(encoding="utf-8"))
            winner = next(name for name, state in outcomes if state == "acquired")
            self.assertEqual(active["transaction_id"], winner)
            with self.assertRaises(FileExistsError):
                with acquire_output_lock(output_dir, "d" * 64, transaction_id="任务D"):
                    pass
            self.assertEqual(json.loads(lock_path.read_text(encoding="utf-8"))["transaction_id"], winner)
            release.set()
            for thread in threads:
                thread.join(timeout=10)
            self.assertEqual(sorted(state for _, state in outcomes), ["acquired", "blocked"])

    def test_deterministic_three_party_aba_process_sequence_keeps_active_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output_dir = root / "output"
            ready = root / "ready"
            release = root / "release"
            script_dir = str(Path(splitter.__file__).parent)
            holder_code = (
                "import sys,time\n"
                "from pathlib import Path\n"
                "sys.path.insert(0,sys.argv[1])\n"
                "from split_text import acquire_output_lock\n"
                "with acquire_output_lock(Path(sys.argv[2]),'e'*64,transaction_id='活动任务C'):\n"
                " Path(sys.argv[3]).write_text('ready',encoding='utf-8')\n"
                " while not Path(sys.argv[4]).exists(): time.sleep(0.002)\n"
            )
            contender_code = (
                "import sys\n"
                "from pathlib import Path\n"
                "sys.path.insert(0,sys.argv[1])\n"
                "from split_text import acquire_output_lock\n"
                "try:\n"
                " with acquire_output_lock(Path(sys.argv[2]),'f'*64,transaction_id=sys.argv[3]):\n"
                "  pass\n"
                "except FileExistsError:\n"
                " raise SystemExit(2)\n"
            )
            holder = subprocess.Popen([
                sys.executable, "-B", "-c", holder_code,
                script_dir, str(output_dir), str(ready), str(release),
            ])
            for _ in range(5000):
                if ready.exists():
                    break
                if holder.poll() is not None:
                    self.fail(f"持锁进程提前退出：{holder.returncode}")
                threading.Event().wait(0.002)
            self.assertTrue(ready.exists())
            contenders = [
                subprocess.Popen([
                    sys.executable, "-B", "-c", contender_code,
                    script_dir, str(output_dir), transaction_id,
                ])
                for transaction_id in ("接管者B", "任务D")
            ]
            self.assertEqual([process.wait(timeout=20) for process in contenders], [2, 2])
            lock_path = output_dir.parent / f".{output_dir.name}.video-copy-splitter.lock"
            self.assertEqual(json.loads(lock_path.read_text(encoding="utf-8"))["transaction_id"], "活动任务C")
            release.write_text("release", encoding="utf-8")
            self.assertEqual(holder.wait(timeout=20), 0)

    def test_kernel_lock_is_released_automatically_after_process_crash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output_dir = root / "output"
            ready = root / "ready"
            script_dir = str(Path(splitter.__file__).parent)
            crash_code = (
                "import os,sys\n"
                "from pathlib import Path\n"
                "sys.path.insert(0,sys.argv[1])\n"
                "from split_text import acquire_output_lock\n"
                "with acquire_output_lock(Path(sys.argv[2]),'a'*64,transaction_id='崩溃任务'):\n"
                " Path(sys.argv[3]).write_text('ready',encoding='utf-8')\n"
                " os._exit(7)\n"
            )
            process = subprocess.Popen([
                sys.executable, "-B", "-c", crash_code,
                script_dir, str(output_dir), str(ready),
            ])
            self.assertEqual(process.wait(timeout=20), 7)
            self.assertTrue(ready.exists())
            with acquire_output_lock(output_dir, "b" * 64, transaction_id="恢复任务"):
                lock_path = output_dir.parent / f".{output_dir.name}.video-copy-splitter.lock"
                self.assertEqual(json.loads(lock_path.read_text(encoding="utf-8"))["transaction_id"], "恢复任务")

    def test_two_threads_competing_one_hundred_times_never_double_succeed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for iteration in range(100):
                output_dir = root / f"output-{iteration}"
                barrier = threading.Barrier(2)
                outcomes = []
                outcome_lock = threading.Lock()

                def worker(text):
                    outputs = build_outputs(process(text))
                    barrier.wait()
                    try:
                        write_outputs_safely(output_dir, outputs)
                        result = "success"
                    except FileExistsError:
                        result = "conflict"
                    with outcome_lock:
                        outcomes.append(result)

                threads = [
                    threading.Thread(target=worker, args=("甲任务。",)),
                    threading.Thread(target=worker, args=("乙任务。",)),
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
                self.assertEqual(sorted(outcomes), ["conflict", "success"])
                validate_internal_transaction(output_dir)
                source = (output_dir / "00-normalized-source.md").read_text(encoding="utf-8").strip()
                self.assertIn(source, {"甲任务。", "乙任务。"})

    def test_two_processes_writing_same_directory_only_one_succeeds(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output_dir = root / "output"
            start_marker = root / "start"
            script_dir = str(Path(splitter.__file__).parent)
            worker_code = (
                "import sys,time\n"
                "from pathlib import Path\n"
                "sys.path.insert(0,sys.argv[1])\n"
                "from split_text import build_outputs,process,write_outputs_safely\n"
                "while not Path(sys.argv[3]).exists(): time.sleep(0.002)\n"
                "try:\n"
                " write_outputs_safely(Path(sys.argv[2]),build_outputs(process(sys.argv[4])))\n"
                "except FileExistsError:\n"
                " raise SystemExit(2)\n"
            )
            processes = [
                subprocess.Popen([sys.executable, "-B", "-c", worker_code, script_dir, str(output_dir), str(start_marker), text])
                for text in ("进程甲。", "进程乙。")
            ]
            start_marker.write_text("开始", encoding="utf-8")
            return_codes = [process.wait(timeout=20) for process in processes]
            self.assertEqual(sorted(return_codes), [0, 2])
            validate_internal_transaction(output_dir)

    def test_failed_transaction_does_not_delete_foreign_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            foreign_dir = root / "foreign"
            output_dir = root / "output"
            write_outputs_safely(foreign_dir, build_outputs(process("成功任务。")))
            original_validate = splitter.validate_internal_transaction
            calls = 0
            tampered = False

            def replace_after_publish(path, **kwargs):
                nonlocal calls, tampered
                calls += 1
                if Path(path).resolve() == output_dir.resolve() and calls >= 2 and not tampered:
                    tampered = True
                    shutil_target = Path(path)
                    if shutil_target.exists():
                        shutil.rmtree(shutil_target)
                    os.replace(foreign_dir, output_dir)
                    raise OSError("模拟发布后被其他事务替换")
                return original_validate(path, **kwargs)

            with patch("split_text.validate_internal_transaction", side_effect=replace_after_publish):
                with self.assertRaises(RuntimeError):
                    write_outputs_safely(output_dir, build_outputs(process("失败任务。")))
            manifest = original_validate(output_dir)
            self.assertEqual((output_dir / "00-normalized-source.md").read_text(encoding="utf-8").strip(), "成功任务。")
            self.assertTrue(manifest["transaction_id"])

    def test_final_delivery_directory_must_contain_exactly_three_files(self):
        with tempfile.TemporaryDirectory() as temp:
            delivery_dir = Path(temp) / "delivery"
            delivery_dir.mkdir()
            for name in FINAL_DELIVERY_NAMES:
                (delivery_dir / name).write_text("测试", encoding="utf-8")
            self.assertEqual(validate_final_delivery_dir(delivery_dir), delivery_dir.resolve())
            (delivery_dir / "project-data.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_final_delivery_dir(delivery_dir)

    def test_series_delivery_contains_three_files_per_episode(self):
        with tempfile.TemporaryDirectory() as temp:
            delivery_dir = Path(temp) / "delivery"
            delivery_dir.mkdir()
            names = final_delivery_names(2)
            self.assertEqual(len(names), 6)
            for name in names:
                (delivery_dir / name).write_text("干净正文。", encoding="utf-8")
            self.assertEqual(validate_final_delivery_dir(delivery_dir, episode_count=2), delivery_dir.resolve())

    def test_series_voice_copy_rejects_episode_separator_inside_text(self):
        with tempfile.TemporaryDirectory() as temp:
            delivery_dir = Path(temp) / "delivery"
            delivery_dir.mkdir()
            for name in final_delivery_names(2):
                content = "第01集\n正文。" if name.endswith("音色克隆文案.txt") else "测试"
                (delivery_dir / name).write_text(content, encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_final_delivery_dir(delivery_dir, episode_count=2)

    def test_final_delivery_rejects_overlong_smart_transcript_line(self):
        with tempfile.TemporaryDirectory() as temp:
            delivery_dir = Path(temp) / "delivery"
            delivery_dir.mkdir()
            for name in FINAL_DELIVERY_NAMES:
                content = "一二三四五六七八九十甲乙丙丁。" if name.startswith("02-") else "测试"
                (delivery_dir / name).write_text(content, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "超过13个中文字符或数字"):
                validate_final_delivery_dir(delivery_dir)


if __name__ == "__main__":
    unittest.main()
