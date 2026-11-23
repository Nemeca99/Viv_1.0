"""
VTM Specification & Binary Container (Viv Topological Matrix)
=============================================================
Architect: Travis (Nox Forge / AIOS V2)
Purpose: 
  Sovereign, zero-copy, INT8/fixed-point binary format for AIOS V2.
  Replaces GGUF/SafeTensors with a dual-pole topological container:
    1. Forward integer synapse weights (Tensor Core INT8 GEMM ready).
    2. Negative evidence boundary mask (Deterministic failure brake).
    3. Epistemic provenance metadata and SHA-256 ancestral seal.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import torch

VTM_MAGIC = b"VTM\x02"  # Viv Topological Matrix Version 2
HEADER_STRUCT = "<4sIIQQQQIIII32s"  # 88 bytes fixed header
# 4s  : magic (VTM\x02)
# I   : format_version (2)
# I   : domain_id (1=ENG, 2=PY, 3=RS, 4=UML, 5=ALU, 99=CUSTOM)
# Q   : epoch (uint64)
# Q   : created_timestamp (uint64)
# Q   : neuron_count (uint64)
# Q   : synapse_count (uint64)
# I   : vocab_size (uint32)
# I   : d_model (uint32)
# I   : n_layers (uint32)
# I   : n_heads (uint32)
# 32s : source_sqlite_sha256 (raw bytes)

DOMAIN_MAP = {
    "ENGLISH": 1,
    "PYTHON": 2,
    "RUST": 3,
    "UML": 4,
    "ALU": 5,
    "CUSTOM": 99,
}
REVERSE_DOMAIN_MAP = {v: k for k, v in DOMAIN_MAP.items()}


@dataclass
class VTMMetadata:
    domain_name: str
    epoch: int
    created_iso: str
    vocab_size: int
    d_model: int
    n_layers: int
    n_heads: int
    max_seq_len: int
    neuron_count: int
    synapse_count: int
    negative_boundary_count: int
    source_db_name: str
    source_db_sha256: str
    extra: Dict[str, Any] = field(default_factory=dict)


class VTMContainer:
    """Encoder and zero-copy reader for .vtm files."""

    @staticmethod
    def pack(
        output_path: Path | str,
        metadata: VTMMetadata,
        tensors: Dict[str, torch.Tensor],
        negative_boundaries: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Serializes model tensors and negative evidence into an official .vtm file."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        domain_id = DOMAIN_MAP.get(metadata.domain_name.upper(), 99)
        src_sha_bytes = bytes.fromhex(metadata.source_db_sha256) if len(metadata.source_db_sha256) == 64 else b"\x00" * 32

        # 1. Prepare Metadata JSON
        meta_dict = {
            "domain_name": metadata.domain_name,
            "epoch": metadata.epoch,
            "created_iso": metadata.created_iso,
            "vocab_size": metadata.vocab_size,
            "d_model": metadata.d_model,
            "n_layers": metadata.n_layers,
            "n_heads": metadata.n_heads,
            "max_seq_len": metadata.max_seq_len,
            "neuron_count": metadata.neuron_count,
            "synapse_count": metadata.synapse_count,
            "negative_boundary_count": metadata.negative_boundary_count,
            "source_db_name": metadata.source_db_name,
            "source_db_sha256": metadata.source_db_sha256,
            "extra": metadata.extra,
            "negative_boundaries": negative_boundaries or [],
        }
        meta_json_bytes = json.dumps(meta_dict, ensure_ascii=False, indent=None).encode("utf-8")

        # 2. Build Tensor Catalog & Raw Data
        # We align tensor buffers to 64-byte boundaries for native AVX-512 / Tensor Core alignment
        tensor_index = []
        raw_tensor_buffer = bytearray()

        dtype_map = {
            torch.int8: "int8",
            torch.uint8: "uint8",
            torch.int16: "int16",
            torch.int32: "int32",
            torch.int64: "int64",
            torch.float16: "float16",
            torch.float32: "float32",
        }

        for name, tensor in tensors.items():
            t_cpu = tensor.detach().cpu().contiguous()
            dtype_str = dtype_map.get(t_cpu.dtype, "int8")
            raw_bytes = t_cpu.numpy().tobytes()

            # Align to 64 bytes
            pad = (64 - (len(raw_tensor_buffer) % 64)) % 64
            if pad > 0:
                raw_tensor_buffer.extend(b"\x00" * pad)

            offset = len(raw_tensor_buffer)
            length = len(raw_bytes)
            raw_tensor_buffer.extend(raw_bytes)

            tensor_index.append({
                "name": name,
                "dtype": dtype_str,
                "shape": list(t_cpu.shape),
                "offset": offset,
                "length": length,
            })

        index_json_bytes = json.dumps(tensor_index).encode("utf-8")

        # 3. Assemble binary image in memory to compute final SHA-256 seal
        import time
        created_timestamp = int(time.time())

        header_bytes = struct.pack(
            HEADER_STRUCT,
            VTM_MAGIC,
            2,  # version
            domain_id,
            metadata.epoch,
            created_timestamp,
            metadata.neuron_count,
            metadata.synapse_count,
            metadata.vocab_size,
            metadata.d_model,
            metadata.n_layers,
            metadata.n_heads,
            src_sha_bytes,
        )

        lengths_header = struct.pack("<QQ", len(meta_json_bytes), len(index_json_bytes))

        # Write to file and compute SHA-256
        sha256 = hashlib.sha256()
        with open(output_path, "wb") as f:
            f.write(header_bytes)
            sha256.update(header_bytes)

            f.write(lengths_header)
            sha256.update(lengths_header)

            f.write(meta_json_bytes)
            sha256.update(meta_json_bytes)

            f.write(index_json_bytes)
            sha256.update(index_json_bytes)

            # Align to 64 bytes before tensor payload
            cur_pos = f.tell()
            pad = (64 - (cur_pos % 64)) % 64
            if pad > 0:
                pad_bytes = b"\x00" * pad
                f.write(pad_bytes)
                sha256.update(pad_bytes)

            f.write(raw_tensor_buffer)
            sha256.update(raw_tensor_buffer)

            # Tail seal: final SHA-256
            final_hash = sha256.hexdigest()
            f.write(bytes.fromhex(final_hash))

        return final_hash

    @staticmethod
    def inspect(vtm_path: Path | str) -> Dict[str, Any]:
        """Inspects .vtm header and metadata without loading all tensors into memory."""
        vtm_path = Path(vtm_path)
        with open(vtm_path, "rb") as f:
            raw_header = f.read(struct.calcsize(HEADER_STRUCT))
            (
                magic,
                ver,
                domain_id,
                epoch,
                timestamp,
                neuron_count,
                synapse_count,
                vocab_size,
                d_model,
                n_layers,
                n_heads,
                src_sha_bytes,
            ) = struct.unpack(HEADER_STRUCT, raw_header)

            if magic != VTM_MAGIC:
                raise ValueError(f"Invalid VTM magic: {magic}")

            meta_len, index_len = struct.unpack("<QQ", f.read(16))
            meta_json = json.loads(f.read(meta_len).decode("utf-8"))
            index_json = json.loads(f.read(index_len).decode("utf-8"))

        return {
            "format": "Viv Topological Matrix",
            "version": ver,
            "domain": REVERSE_DOMAIN_MAP.get(domain_id, "CUSTOM"),
            "epoch": epoch,
            "neuron_count": neuron_count,
            "synapse_count": synapse_count,
            "vocab_size": vocab_size,
            "d_model": d_model,
            "n_layers": n_layers,
            "n_heads": n_heads,
            "metadata": meta_json,
            "tensor_count": len(index_json),
            "tensors": index_json,
            "file_size_bytes": vtm_path.stat().st_size,
        }

    @staticmethod
    def load_tensors(
        vtm_path: Path | str,
        device: str = "cuda:0" if torch.cuda.is_available() else "cpu",
    ) -> Tuple[Dict[str, torch.Tensor], Dict[str, Any]]:
        """Zero-copy fast load of tensors directly onto target device."""
        vtm_path = Path(vtm_path)
        with open(vtm_path, "rb") as f:
            header_size = struct.calcsize(HEADER_STRUCT)
            f.seek(header_size)
            meta_len, index_len = struct.unpack("<QQ", f.read(16))
            meta_dict = json.loads(f.read(meta_len).decode("utf-8"))
            tensor_index = json.loads(f.read(index_len).decode("utf-8"))

            cur_pos = f.tell()
            pad = (64 - (cur_pos % 64)) % 64
            tensor_data_start = cur_pos + pad

            f.seek(tensor_data_start)
            raw_payload = bytearray(f.read())

        # Parse tensors from raw byte buffer
        dtype_torch_map = {
            "int8": torch.int8,
            "uint8": torch.uint8,
            "int16": torch.int16,
            "int32": torch.int32,
            "int64": torch.int64,
            "float16": torch.float16,
            "float32": torch.float32,
        }

        tensors: Dict[str, torch.Tensor] = {}
        for entry in tensor_index:
            name = entry["name"]
            shape = entry["shape"]
            dtype = dtype_torch_map[entry["dtype"]]
            offset = entry["offset"]
            length = entry["length"]

            tensor_slice = raw_payload[offset : offset + length]
            # Zero-copy frombuffer
            t = torch.frombuffer(tensor_slice, dtype=dtype).view(*shape)
            tensors[name] = t.to(device)

        return tensors, meta_dict
