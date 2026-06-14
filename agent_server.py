import os

import shutil
from typing import List
from fastapi import FastAPI, HTTPException, UploadFile, File
from pydantic import BaseModel
from rapidfuzz import fuzz

app = FastAPI()

BASE_DIR = r"C:\Users\安\Desktop\云计算与大数据\期末任务\knowledge"


class SearchRequest(BaseModel):
    keyword: str


class OpenRequest(BaseModel):
    filename: str


def search_files(keyword: str, top_k=5):

    results = []

    for root, dirs, files in os.walk(BASE_DIR):

        for file in files:

            score = fuzz.partial_ratio(
                keyword.lower(),
                file.lower()
            )

            if score > 30:
                results.append({
                    "filename": file,
                    "path": os.path.join(root, file),
                    "score": score
                })

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return results[:top_k]


@app.post("/search")
async def search(req: SearchRequest):

    files = search_files(req.keyword)

    return {
        "keyword": req.keyword,
        "count": len(files),
        "files": files
    }


@app.post("/open")
async def open_file(req: OpenRequest):

    target_path = None

    for root, dirs, files in os.walk(BASE_DIR):

        if req.filename in files:
            target_path = os.path.join(root, req.filename)
            break

    if not target_path:
        raise HTTPException(
            status_code=404,
            detail="文件不存在"
        )

    try:

        os.startfile(target_path)

        return {
            "status": "success",
            "filename": req.filename
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

@app.post("/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    """处理多个文件批量上传并保存到知识库目录"""
    uploaded_titles = []
    failed_files = []

    # 循环处理每一个上传上来的文件
    for file in files:
        file_location = os.path.join(BASE_DIR, file.filename)
        try:
            with open(file_location, "wb+") as file_object:
                shutil.copyfileobj(file.file, file_object)
            uploaded_titles.append(file.filename)
        except Exception as e:
            failed_files.append({"filename": file.filename, "error": str(e)})
            
    # 返回批量处理的结果报告
    return {
        "status": "success" if not failed_files else "partial_success",
        "uploaded_count": len(uploaded_titles),
        "uploaded_files": uploaded_titles,
        "failed_files": failed_files,
        "message": f"成功入库 {len(uploaded_titles)} 个文件。" + (f" 失败 {len(failed_files)} 个。" if failed_files else "")
    }

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8080
    )