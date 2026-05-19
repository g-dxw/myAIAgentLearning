def ok(data=None, message="success"):
    return {"code": 200, "message": message, "data": data}


def ok_page(data, total, page, page_size):
    return {
        "code": 200,
        "message": "success",
        "data": data,
        "total": total,
        "page": page,
        "pageSize": page_size,
    }


def fail(code=400, message="error", data=None):
    return {"code": code, "message": message, "data": data}
